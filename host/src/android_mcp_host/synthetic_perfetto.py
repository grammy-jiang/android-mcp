"""H5.c owner-pinned private synthetic Perfetto fixture; real tracing disabled."""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_debug_support import verified_fake_target
from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.perfetto_trace_control import cancel_trace
from android_mcp_host.perfetto_trace_receipts import replay_trace
from android_mcp_host.perfetto_trace_support import (
    TRACE_VERSION,
    InvalidTrace,
    plan_digest,
    reply,
    sanitize_trace,
    valid_capture,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.ui_action_support import valid_lifecycle_job, valid_request_id

_WORKER = "h5c-synthetic-perfetto"
_TIMEOUT_S = 3.0


@dataclass(frozen=True, slots=True)
class PerfettoApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    profile: str
    purpose: str
    valid_until_epoch: float
    ttl_s: int
    debuggable: bool
    trace_supported: bool


@dataclass(frozen=True, slots=True)
class PerfettoFrame:
    payload: bytes
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    profile: str
    duration_s: int
    fixture_version: str
    complete: bool
    synthetic: bool


FixtureTrace = Callable[
    [str, str, str, str, int, int, float, threading.Event],
    PerfettoFrame,
]


def get_perfetto_schema() -> dict[str, Any]:
    content: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-perfetto.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(content, dict):
        raise ValueError("Invalid private synthetic Perfetto schema")
    return content


class PerfettoService:
    """Trusted test-only callbacks; expiring private artifact/receipt replay."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        approval: PerfettoApproval | None = None,
        fixture_trace: FixtureTrace | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid Perfetto synthetic owner or lifecycle")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._approval = approval
        self._fixture = fixture_trace
        self._clock = clock
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    def _signal_stop(self, jid: str) -> None:
        with self._guard:
            if jid in self._active:
                self._active[jid].set()

    @staticmethod
    def _slot(lid: str) -> str:
        return "h5c-perfetto-" + lid

    def _approved(self, handle: str, lid: str, profile: str, ttl_s: int) -> bool:
        grant = self._approval
        if grant is None:
            return False
        try:
            remaining = grant.valid_until_epoch - self._clock()
        except (ValueError, ArithmeticError, TypeError):
            return False
        return (
            grant.owner == self._owner
            and grant.avd_handle == handle
            and grant.lifecycle_job_id == lid
            and grant.profile == profile
            and grant.purpose == "private-synthetic-perfetto"
            and type(grant.valid_until_epoch) in (int, float)
            and type(grant.ttl_s) is int
            and math.isfinite(remaining)
            and 0 < remaining <= 300
            and 1 <= ttl_s <= grant.ttl_s <= 300
            and remaining >= ttl_s
        )

    def _base(
        self, info: dict[str, Any], lid: str, profile: str, duration_s: int, max_bytes: int
    ) -> dict[str, Any]:
        return {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle": lid,
            "profile": profile,
            "duration_s": duration_s,
            "max_bytes": max_bytes,
        }

    def _finish_bad(
        self,
        info: dict[str, Any],
        jid: str,
        generation: int,
        code: str,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        self._jobs.complete(
            self._owner,
            jid,
            _WORKER,
            generation,
            info["handle"],
            authorized=True,
            failure_code=code,
        )
        return reply("failed", state="unknown", job_id=jid, error=code, **base)

    def _execute(
        self,
        info: dict[str, Any],
        lid: str,
        request: str,
        profile: str,
        duration_s: int,
        max_bytes: int,
        ttl_s: int,
    ) -> dict[str, Any]:
        base = self._base(info, lid, profile, duration_s, max_bytes)
        digest = plan_digest(info["handle"], lid, request, profile, duration_s, max_bytes, ttl_s)
        try:
            prior = self._jobs.lookup_request(self._owner, self._slot(lid), digest, info["handle"])
            if prior is not None:
                return replay_trace(self._artifacts, self._artifact_owner, prior, **base)
            if any(
                row["job_id"] != lid
                and row["state"] in {"prepared", "queued", "running", "uncertain"}
                for row in self._jobs.list_status(self._owner)
            ):
                return reply("blocked", error="RECOVERY_REQUIRED", **base)
            job = self._jobs.prepare(
                self._owner,
                self._slot(lid),
                digest,
                identity=info["handle"],
                authorized=True,
            )
            jid = str(job["job_id"])
            self._jobs.queue(self._owner, jid, identity=info["handle"], authorized=True)
            running = self._jobs.claim(
                self._owner,
                jid,
                _WORKER,
                info["handle"],
                authorized=True,
            )
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return reply("blocked", error=code, **base)
        stop = threading.Event()
        with self._guard:
            self._active[jid] = stop
        handles: list[str] = []
        completed = False
        try:
            assert self._fixture is not None and self._approval is not None
            started = time.monotonic()
            frame = self._fixture(
                info["name"],
                info["handle"],
                lid,
                profile,
                duration_s,
                max_bytes,
                _TIMEOUT_S,
                stop,
            )
            if stop.is_set():
                return reply("uncertain", state="unknown", job_id=jid, error="CANCELLED", **base)
            if time.monotonic() - started > _TIMEOUT_S:
                return reply("uncertain", state="unknown", job_id=jid, error="TIMEOUT", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return reply(
                    "uncertain",
                    state="unknown",
                    job_id=jid,
                    error="UNVERIFIED_TARGET",
                    **base,
                )
            if not self._approved(info["handle"], lid, profile, ttl_s):
                return reply(
                    "uncertain",
                    state="unknown",
                    job_id=jid,
                    error="CONSENT_REQUIRED",
                    **base,
                )
            if (
                type(frame) is not PerfettoFrame
                or frame.avd_name != info["name"]
                or frame.avd_handle != info["handle"]
                or frame.lifecycle_job_id != lid
                or frame.profile != profile
                or frame.duration_s != duration_s
                or frame.fixture_version != "mcp-fixture-1"
                or frame.complete is not True
                or frame.synthetic is not True
                or type(frame.payload) is not bytes
            ):
                response = self._finish_bad(
                    info,
                    jid,
                    running["generation"],
                    "BAD_FRAME",
                    base,
                )
                completed = True
                return response
            try:
                sanitized, samples, removed = sanitize_trace(
                    frame.payload,
                    profile=profile,
                    duration_s=duration_s,
                    max_bytes=max_bytes,
                )
            except InvalidTrace:
                code = "TRACE_TOO_LARGE" if len(frame.payload) > max_bytes else "BAD_TRACE"
                response = self._finish_bad(
                    info,
                    jid,
                    running["generation"],
                    code,
                    base,
                )
                completed = True
                return response
            trace = self._artifacts.put(
                self._artifact_owner,
                sanitized,
                mime_type="application/json",
                ttl_s=ttl_s,
            )
            handles.append(trace["handle"])
            receipt = {
                "purpose": "h5c-sanitized-synthetic-perfetto-v1",
                "schema_version": 1,
                "trace_format": TRACE_VERSION,
                "fixture_version": "mcp-fixture-1",
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "profile": profile,
                "duration_s": duration_s,
                "max_bytes": max_bytes,
                "artifact_handle": trace["handle"],
                "sha256": trace["sha256"],
                "size_bytes": len(sanitized),
                "sample_count": samples,
                "redacted_lines": removed,
                "retention_seconds": ttl_s,
                "synthetic_fixture_only": True,
                "sanitized_only": True,
            }
            serialized = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            manifest = self._artifacts.put(
                self._artifact_owner,
                serialized,
                mime_type="application/json",
                ttl_s=ttl_s,
            )
            handles.append(manifest["handle"])
            if stop.is_set():
                return reply("uncertain", state="unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return reply(
                    "uncertain",
                    state="unknown",
                    job_id=jid,
                    error="UNVERIFIED_TARGET",
                    **base,
                )
            if not self._approved(info["handle"], lid, profile, ttl_s):
                return reply(
                    "uncertain",
                    state="unknown",
                    job_id=jid,
                    error="CONSENT_REQUIRED",
                    **base,
                )
            self._jobs.complete(
                self._owner,
                jid,
                _WORKER,
                running["generation"],
                info["handle"],
                authorized=True,
                result_digest=manifest["sha256"],
            )
            completed = True
            return reply(
                "ok",
                state="synthetic_sanitized",
                job_id=jid,
                artifact_handle=trace["handle"],
                receipt_handle=manifest["handle"],
                sha256=trace["sha256"],
                size_bytes=len(sanitized),
                sample_count=samples,
                redacted_lines=removed,
                ttl_s=ttl_s,
                **base,
            )
        except subprocess.TimeoutExpired:
            return reply("uncertain", state="unknown", job_id=jid, error="TIMEOUT", **base)
        except (
            ArtifactStoreError,
            JobStoreError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            KeyError,
            subprocess.SubprocessError,
        ):
            return reply("uncertain", state="unknown", job_id=jid, error="RUNNER_FAILED", **base)
        finally:
            with self._guard:
                self._active.pop(jid, None)
            if not completed:
                for handle in handles:
                    try:
                        self._artifacts.revoke(self._artifact_owner, handle)
                    except ArtifactStoreError:
                        pass
                try:
                    self._jobs.cancel(
                        self._owner,
                        jid,
                        identity=info["handle"],
                        authorized=True,
                    )
                except JobStoreError:
                    pass

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        *,
        profile: str = "sched-lite-v1",
        duration_s: int = 3,
        max_bytes: int = 131072,
        ttl_s: int = 60,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"plan", "capture", "cancel"}:
            return reply("blocked", error="INVALID_ACTION")
        if not isinstance(profile, str) or profile not in {"sched-lite-v1", "frames-lite-v1"}:
            return reply("blocked", error="INVALID_PROFILE")
        if (
            not valid_lifecycle_job(lifecycle_job_id)
            or not valid_capture(profile, duration_s, max_bytes, ttl_s)
            or (action != "plan" and not valid_request_id(request_id))
            or (action == "cancel" and not valid_lifecycle_job(job_id))
            or (action != "cancel" and job_id is not None)
        ):
            return reply("blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return reply("blocked", error="NOT_OWNED")
        base = self._base(info, lifecycle_job_id, profile, duration_s, max_bytes)
        if action == "plan":
            return reply("planned", **base)
        assert request_id is not None
        if action == "cancel":
            assert job_id is not None
            return cancel_trace(
                self._jobs,
                self._owner,
                info,
                lifecycle_job_id,
                request_id,
                profile,
                duration_s,
                max_bytes,
                ttl_s,
                job_id,
                self._signal_stop,
            )
        if not self._approved(info["handle"], lifecycle_job_id, profile, ttl_s):
            return reply("blocked", error="CONSENT_REQUIRED", **base)
        assert self._approval is not None
        if self._approval.debuggable is not True:
            return reply("blocked", error="NOT_DEBUGGABLE", **base)
        if self._approval.trace_supported is not True:
            return reply("blocked", error="TRACE_UNSUPPORTED", **base)
        if self._fixture is None:
            return reply("blocked", error="EXECUTION_DISABLED", **base)
        if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
            return reply("blocked", error="UNVERIFIED_TARGET", **base)
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return reply("blocked", error="JOB_UNAVAILABLE", **base)
        if fd is None:
            return reply("blocked", error="RECOVERY_REQUIRED", **base)
        try:
            return self._execute(
                info,
                lifecycle_job_id,
                request_id,
                profile,
                duration_s,
                max_bytes,
                ttl_s,
            )
        finally:
            os.close(fd)

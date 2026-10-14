"""H5.a private synthetic sanitized bugreport: real diagnostic reads disabled."""

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
from android_mcp_host.bugreport_control import (
    bugreport_digest,
    bugreport_slot,
    cancel_bugreport,
)
from android_mcp_host.bugreport_receipts import _reply, replay_bugreport
from android_mcp_host.bugreport_support import (
    MAX_ZIP_BYTES,
    InvalidBugreport,
    sanitize_bugreport,
    verify_bugreport_frame,
)
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_debug_support import verified_fake_target
from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.ui_action_support import valid_lifecycle_job, valid_request_id

_WORKER = "h5a-private-synthetic-bugreport"
_TIMEOUT_S = 3.0


@dataclass(frozen=True, slots=True)
class BugreportApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    purpose: str
    valid_until_epoch: float
    ttl_s: int


@dataclass(frozen=True, slots=True)
class BugreportFrame:
    payload: bytes
    status_line: str
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    complete: bool
    synthetic: bool


ReportCollector = Callable[[str, str, str, float, int, threading.Event], BugreportFrame]


def get_bugreport_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-private-bugreport.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged synthetic bugreport schema")
    return value


class BugreportService:
    """Durable one-shot fake bugreport; raw diagnostics never stored."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        approval: BugreportApproval | None = None,
        fixture_collect: ReportCollector | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid private bugreport owner configuration")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._approval = approval
        self._fixture = fixture_collect
        self._clock = clock
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    def _signal_stop(self, jid: str) -> None:
        with self._guard:
            if jid in self._active:
                self._active[jid].set()

    def _approved(self, handle: str, lid: str) -> bool:
        grant = self._approval
        if grant is None:
            return False
        try:
            remaining = grant.valid_until_epoch - self._clock()
        except (ValueError, TypeError, ArithmeticError):
            return False
        return (
            grant.owner == self._owner
            and grant.avd_handle == handle
            and grant.lifecycle_job_id == lid
            and grant.purpose == "synthetic-sanitized-bugreport"
            and type(grant.valid_until_epoch) in (int, float)
            and type(grant.ttl_s) is int
            and math.isfinite(remaining)
            and 0 < remaining <= 300
            and 1 <= grant.ttl_s <= 300
        )

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
        return _reply("failed", "unknown", job_id=jid, error=code, **base)

    def _execute(self, info: dict[str, Any], lid: str, request_id: str) -> dict[str, Any]:
        base: dict[str, Any] = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lid,
        }
        digest = bugreport_digest(info["handle"], lid, request_id)
        try:
            prior = self._jobs.lookup_request(
                self._owner,
                bugreport_slot(lid),
                digest,
                info["handle"],
            )
            if prior is not None:
                return replay_bugreport(
                    self._artifacts,
                    self._artifact_owner,
                    prior,
                    name=info["name"],
                    handle=info["handle"],
                    lifecycle_id=lid,
                )
            if any(
                row["job_id"] != lid
                and row["state"] in {"prepared", "queued", "running", "uncertain"}
                for row in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", error="RECOVERY_REQUIRED", **base)
            job = self._jobs.prepare(
                self._owner,
                bugreport_slot(lid),
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
            return _reply("blocked", error=code, **base)
        stop = threading.Event()
        with self._guard:
            self._active[jid] = stop
        handles: list[str] = []
        finished = False
        try:
            assert self._fixture is not None and self._approval is not None
            frame = self._fixture(
                info["name"],
                info["handle"],
                lid,
                _TIMEOUT_S,
                MAX_ZIP_BYTES,
                stop,
            )
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if not self._approved(info["handle"], lid):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            if not verify_bugreport_frame(
                frame,
                expected_type=BugreportFrame,
                name=info["name"],
                handle=info["handle"],
                lifecycle=lid,
            ):
                response = self._finish_bad(
                    info,
                    jid,
                    running["generation"],
                    "BAD_FRAME",
                    base,
                )
                finished = True
                return response
            try:
                sanitized, count = sanitize_bugreport(frame.payload)
            except InvalidBugreport:
                response = self._finish_bad(
                    info,
                    jid,
                    running["generation"],
                    "BAD_ARCHIVE",
                    base,
                )
                finished = True
                return response
            image = self._artifacts.put(
                self._artifact_owner,
                sanitized,
                mime_type="application/zip",
                ttl_s=self._approval.ttl_s,
            )
            handles.append(image["handle"])
            receipt = {
                "purpose": "h5a-private-sanitized-bugreport-v1",
                "schema_version": 1,
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "artifact_handle": image["handle"],
                "sha256": image["sha256"],
                "size_bytes": len(sanitized),
                "redacted_lines": count,
                "retention_seconds": self._approval.ttl_s,
                "synthetic_fixture_only": True,
                "sanitized_only": True,
            }
            blob = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            record = self._artifacts.put(
                self._artifact_owner,
                blob,
                mime_type="application/json",
                ttl_s=self._approval.ttl_s,
            )
            handles.append(record["handle"])
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if not self._approved(info["handle"], lid):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            self._jobs.complete(
                self._owner,
                jid,
                _WORKER,
                running["generation"],
                info["handle"],
                authorized=True,
                result_digest=record["sha256"],
            )
            finished = True
            return _reply(
                "ok",
                "sanitized_synthetic",
                job_id=jid,
                artifact_handle=image["handle"],
                receipt_handle=record["handle"],
                sha256=image["sha256"],
                size_bytes=len(sanitized),
                redacted_lines=count,
                retention_seconds=self._approval.ttl_s,
                **base,
            )
        except subprocess.TimeoutExpired:
            return _reply("uncertain", "unknown", job_id=jid, error="TIMEOUT", **base)
        except (
            ArtifactStoreError,
            JobStoreError,
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            subprocess.SubprocessError,
        ):
            return _reply("uncertain", "unknown", job_id=jid, error="RUNNER_FAILED", **base)
        finally:
            with self._guard:
                self._active.pop(jid, None)
            if not finished:
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
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"plan", "collect", "cancel"}:
            return _reply("blocked", error="INVALID_ACTION")
        if (
            not valid_lifecycle_job(lifecycle_job_id)
            or (action != "plan" and not valid_request_id(request_id))
            or (action == "cancel" and not valid_lifecycle_job(job_id))
        ):
            return _reply("blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lifecycle_job_id}
        if action == "plan":
            return _reply("planned", **base)
        assert request_id is not None
        if action == "cancel":
            assert job_id is not None
            return cancel_bugreport(
                self._jobs,
                self._owner,
                info,
                lifecycle_job_id,
                request_id,
                job_id,
                self._signal_stop,
            )
        if not self._approved(avd_handle, lifecycle_job_id):
            return _reply("blocked", error="CONSENT_REQUIRED", **base)
        if self._fixture is None:
            return _reply("blocked", error="EXECUTION_DISABLED", **base)
        if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
            return _reply("blocked", error="UNVERIFIED_TARGET", **base)
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", error="JOB_UNAVAILABLE", **base)
        if fd is None:
            return _reply("blocked", error="RECOVERY_REQUIRED", **base)
        try:
            return self._execute(info, lifecycle_job_id, request_id)
        finally:
            os.close(fd)

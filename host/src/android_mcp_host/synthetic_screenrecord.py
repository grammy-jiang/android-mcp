"""H4.c owner-pinned synthetic video receipts; no real ADB recording backend.

A production Host can plan but cannot inject a recording fixture or grant.
Only a bounded test-only callback may produce an MP4-shaped fixture, stored
privately with a durable, owner-scoped job receipt and no raw Tool media.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
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
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.screenrecord_receipts import _MIME, _reply, replay_record
from android_mcp_host.screenrecord_support import (
    DEFAULT_DURATION,
    DEFAULT_VIDEO_BYTES,
    InvalidSyntheticVideo,
    valid_record_request,
    validate_video,
)

_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_WORKER = "h4c-synthetic-video-worker"


@dataclass(frozen=True, slots=True)
class RecordApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    purpose: str
    valid_until_epoch: float
    ttl_s: float


@dataclass(frozen=True, slots=True)
class RecordedClip:
    payload: bytes
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    duration_s: int
    display_id: int
    codec: str
    secure_window: bool
    locked_window: bool
    synthetic: bool


Recorder = Callable[[str, str, str, int, int, str, int, threading.Event], RecordedClip]


def get_screenrecord_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-screenrecord.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host video schema")
    return value


class ScreenRecordService:
    """One bounded, expiring, durable fake recording per owned lifecycle."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        approval: RecordApproval | None = None,
        fixture_record: Recorder | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid private synthetic recording ownership")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._approval = approval
        self._fixture = fixture_record
        self._clock = clock
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    @staticmethod
    def _slot(lid: str) -> str:
        return "h4c-record:" + lid

    @staticmethod
    def _digest(
        info: dict[str, Any],
        lid: str,
        request: str,
        duration: int,
        display: int,
        codec: str,
        cap: int,
    ) -> str:
        plan = {
            "purpose": "h4c-synthetic-screenrecord-v1",
            "avd": info["handle"],
            "lifecycle": lid,
            "request_id": request,
            "duration_s": duration,
            "display_id": display,
            "codec": codec,
            "max_bytes": cap,
        }
        return hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()

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
            and grant.purpose == "synthetic-video-recording"
            and type(grant.valid_until_epoch) in (int, float)
            and type(grant.ttl_s) in (int, float)
            and math.isfinite(remaining)
            and math.isfinite(grant.ttl_s)
            and 0 < remaining <= 300
            and 1 <= grant.ttl_s <= 300
        )

    def _finish_bad(
        self,
        info: dict[str, Any],
        lid: str,
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
            failure_code=code,
            authorized=True,
        )
        return _reply(
            "blocked" if code == "SECURE_CONTENT" else "failed",
            "unknown",
            job_id=jid,
            error=code,
            **base,
        )

    def _perform(
        self,
        info: dict[str, Any],
        lid: str,
        request: str,
        duration: int,
        display: int,
        codec: str,
        cap: int,
    ) -> dict[str, Any]:
        base = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lid,
            "duration_s": duration,
            "display_id": display,
            "codec": codec,
            "max_bytes": cap,
        }
        digest = self._digest(info, lid, request, duration, display, codec, cap)
        try:
            prior = self._jobs.lookup_request(self._owner, self._slot(lid), digest, info["handle"])
            if prior is not None:
                return replay_record(
                    self._artifacts,
                    self._artifact_owner,
                    prior,
                    info,
                    lid,
                    duration,
                    display,
                    codec,
                    cap,
                )
            if any(
                row["job_id"] != lid
                and row["state"] in {"prepared", "queued", "running", "uncertain"}
                for row in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", error="RECOVERY_REQUIRED", **base)
            record = self._jobs.prepare(
                self._owner,
                self._slot(lid),
                digest,
                identity=info["handle"],
                authorized=True,
            )
            jid = str(record["job_id"])
            self._jobs.queue(self._owner, jid, identity=info["handle"], authorized=True)
            running = self._jobs.claim(self._owner, jid, _WORKER, info["handle"], authorized=True)
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return _reply("blocked", error=code, **base)
        cancel = threading.Event()
        with self._guard:
            self._active[jid] = cancel
        handles: list[str] = []
        finished = False
        try:
            assert self._fixture is not None and self._approval is not None
            frame = self._fixture(
                info["name"], info["handle"], lid, duration, display, codec, cap, cancel
            )
            if cancel.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if not self._approved(info["handle"], lid):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            if (
                type(frame) is not RecordedClip
                or frame.avd_name != info["name"]
                or frame.avd_handle != info["handle"]
                or frame.lifecycle_job_id != lid
                or frame.duration_s != duration
                or frame.display_id != display
                or frame.codec != codec
                or frame.synthetic is not True
                or type(frame.secure_window) is not bool
                or type(frame.locked_window) is not bool
            ):
                response = self._finish_bad(
                    info, lid, jid, running["generation"], "BAD_FRAME", base
                )
                finished = True
                return response
            if frame.secure_window or frame.locked_window:
                response = self._finish_bad(
                    info, lid, jid, running["generation"], "SECURE_CONTENT", base
                )
                finished = True
                return response
            try:
                validate_video(frame.payload, maximum=cap)
            except InvalidSyntheticVideo:
                response = self._finish_bad(
                    info, lid, jid, running["generation"], "BAD_VIDEO", base
                )
                finished = True
                return response
            video = self._artifacts.put(
                self._artifact_owner,
                frame.payload,
                mime_type=_MIME,
                ttl_s=self._approval.ttl_s,
            )
            handles.append(video["handle"])
            receipt = {
                "purpose": "h4c-synthetic-screenrecord-v1",
                "schema_version": 1,
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "duration_s": duration,
                "display_id": display,
                "codec": codec,
                "artifact_handle": video["handle"],
                "sha256": video["sha256"],
                "synthetic_fixture_only": True,
            }
            blob = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            proof = self._artifacts.put(
                self._artifact_owner,
                blob,
                mime_type="application/json",
                ttl_s=self._approval.ttl_s,
            )
            handles.append(proof["handle"])
            if cancel.is_set() or not self._approved(info["handle"], lid):
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            self._jobs.complete(
                self._owner,
                jid,
                _WORKER,
                running["generation"],
                info["handle"],
                authorized=True,
                result_digest=proof["sha256"],
            )
            finished = True
            return _reply(
                "ok",
                "captured_synthetic",
                job_id=jid,
                artifact_handle=video["handle"],
                receipt_handle=proof["handle"],
                sha256=video["sha256"],
                size_bytes=video["size_bytes"],
                **base,
            )
        except subprocess.TimeoutExpired:
            return _reply("uncertain", "unknown", job_id=jid, error="TIMEOUT", **base)
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            ArtifactStoreError,
            JobStoreError,
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
                    self._jobs.cancel(self._owner, jid, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass

    def _cancel(
        self,
        info: dict[str, Any],
        lid: str,
        request: str,
        job_id: str,
        duration: int,
        display: int,
        codec: str,
        cap: int,
    ) -> dict[str, Any]:
        base = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lid,
            "job_id": job_id,
            "duration_s": duration,
            "display_id": display,
            "codec": codec,
            "max_bytes": cap,
        }
        digest = self._digest(info, lid, request, duration, display, codec, cap)
        try:
            prior = self._jobs.lookup_request(self._owner, self._slot(lid), digest, info["handle"])
            if prior is None or prior["job_id"] != job_id:
                return _reply("blocked", error="NOT_ACTIVE", **base)
            if prior["state"] == "uncertain":
                return _reply("uncertain", "unknown", error="CANCELLED", **base)
            if prior["state"] not in {"prepared", "queued", "running"}:
                return _reply("blocked", error="NOT_ACTIVE", **base)
            self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            with self._guard:
                if job_id in self._active:
                    self._active[job_id].set()
            return _reply("uncertain", "unknown", error="CANCELLED", **base)
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return _reply("blocked", error=code, **base)

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        *,
        duration_s: int = DEFAULT_DURATION,
        display_id: int = 0,
        codec: str = "h264",
        max_bytes: int = DEFAULT_VIDEO_BYTES,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"plan", "record", "cancel"}:
            return _reply("blocked", error="INVALID_ACTION")
        if (
            not isinstance(lifecycle_job_id, str)
            or _JOB.fullmatch(lifecycle_job_id) is None
            or not valid_record_request(duration_s, display_id, codec, max_bytes)
            or (
                action != "plan"
                and (not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None)
            )
            or (
                action == "cancel"
                and (not isinstance(job_id, str) or _JOB.fullmatch(job_id) is None)
            )
        ):
            return _reply("blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        base = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lifecycle_job_id,
            "duration_s": duration_s,
            "display_id": display_id,
            "codec": codec,
            "max_bytes": max_bytes,
        }
        if action == "plan":
            return _reply("planned", **base)
        assert request_id is not None
        if action == "cancel":
            assert job_id is not None
            return self._cancel(
                info,
                lifecycle_job_id,
                request_id,
                job_id,
                duration_s,
                display_id,
                codec,
                max_bytes,
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
            return self._perform(
                info,
                lifecycle_job_id,
                request_id,
                duration_s,
                display_id,
                codec,
                max_bytes,
            )
        finally:
            os.close(fd)

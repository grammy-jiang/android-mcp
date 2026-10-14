"""H4.e bounded owner-scoped synthetic file import, real device writes disabled."""

from __future__ import annotations

import hashlib
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
from android_mcp_host.file_pull_support import valid_synthetic_package
from android_mcp_host.file_push_control import cancel_import
from android_mcp_host.file_push_frame import PushFrame, check_push_frame
from android_mcp_host.file_push_receipts import _reply, replay_import
from android_mcp_host.file_push_support import (
    DEFAULT_PUSH_BYTES,
    approved_destination,
    fixture_signature,
    plan_digest,
    request_slot,
    valid_fixture_key,
    valid_request,
    valid_signature,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_WORKER = "h4e-synthetic-private-file-import"


@dataclass(frozen=True, slots=True)
class PushApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    package_id: str
    destination_path: str
    artifact_handle: str
    artifact_sha256: str
    mime_type: str
    purpose: str
    signature: str
    valid_until_epoch: float


PushWriter = Callable[[str, str, str, str, str, bytes, int, threading.Event], PushFrame]


def get_file_push_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-file-push.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged synthetic file-push schema")
    return value


class FilePushService:
    """A trusted test runner may mutate only a fake, privately owned AVD."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        package_id: str,
        approval: PushApproval | None = None,
        fixture_hmac_key: bytes | None = None,
        fixture_writer: PushWriter | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or not valid_synthetic_package(package_id)
            or provisioner.trusted_owner != owner
            or lifecycle._owner != owner
            or lifecycle.provisioner is not provisioner
            or (fixture_hmac_key is not None and not valid_fixture_key(fixture_hmac_key))
        ):
            raise ValueError("Untrusted synthetic private file import composition")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._package = package_id
        self._approval = approval
        self._key = fixture_hmac_key
        self._writer = fixture_writer
        self._clock = clock
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    def _signal_stop(self, jid: str) -> None:
        with self._guard:
            if jid in self._active:
                self._active[jid].set()

    def _approved(
        self,
        handle: str,
        lid: str,
        token: str,
        sha: str,
        dest: str,
        mime: str,
    ) -> bool:
        grant = self._approval
        if grant is None or not valid_fixture_key(self._key):
            return False
        assert isinstance(self._key, bytes)
        try:
            until = grant.valid_until_epoch - self._clock()
        except (TypeError, ValueError, ArithmeticError):
            return False
        return (
            grant.owner == self._owner
            and grant.avd_handle == handle
            and grant.lifecycle_job_id == lid
            and grant.package_id == self._package
            and grant.destination_path == dest
            and grant.artifact_handle == token
            and grant.artifact_sha256 == sha
            and grant.mime_type == mime
            and grant.purpose == "synthetic-atomic-app-import"
            and type(grant.valid_until_epoch) in (int, float)
            and math.isfinite(until)
            and 0 < until <= 300
            and valid_signature(
                grant.signature,
                fixture_signature(
                    self._key,
                    self._owner,
                    handle,
                    lid,
                    self._package,
                    dest,
                    token,
                    sha,
                    mime,
                ),
            )
        )

    def _source(self, token: str, sha: str, mime: str, cap: int) -> bytes | None:
        """Read only owner-bound, integrity-checked private bytes."""
        try:
            metadata = self._artifacts.public_metadata(self._artifact_owner, token)
            if metadata["status"] != "ok":
                return None
            record = metadata["artifact"]
            if (
                record["sha256"] != sha
                or record["mime_type"] != mime
                or not 1 <= record["size_bytes"] <= cap
            ):
                return None
            payload = self._artifacts.read(self._artifact_owner, token)
            if (
                type(payload) is not bytes
                or len(payload) != record["size_bytes"]
                or hashlib.sha256(payload).hexdigest() != sha
            ):
                return None
            return payload
        except (ArtifactStoreError, OSError, TypeError, KeyError, ValueError):
            return None

    def _execute(
        self,
        info: dict[str, Any],
        lid: str,
        token: str,
        sha: str,
        dest: str,
        filename: str,
        mime: str,
        cap: int,
        request: str,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lid,
            "package_id": self._package,
            "filename": filename,
            "artifact_sha256": sha,
            "mime_type": mime,
            "max_bytes": cap,
        }
        digest = plan_digest(info, lid, dest, token, sha, mime, request, cap)
        slot = request_slot(lid, dest)
        try:
            prior = self._jobs.lookup_request(self._owner, slot, digest, info["handle"])
            if prior is not None:
                return replay_import(
                    self._artifacts,
                    self._artifact_owner,
                    prior,
                    info,
                    lid,
                    self._package,
                    dest,
                    filename,
                    token,
                    sha,
                    mime,
                    cap,
                )
            if any(
                item["job_id"] != lid
                and item["state"] in {"prepared", "queued", "running", "uncertain"}
                for item in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", error="RECOVERY_REQUIRED", **base)
            job = self._jobs.prepare(
                self._owner,
                slot,
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
        reports: list[str] = []
        finished = False
        try:
            assert self._writer is not None
            payload = self._source(token, sha, mime, cap)
            if payload is None:
                return _reply("uncertain", "unknown", job_id=jid, error="BAD_ARTIFACT", **base)
            if not self._approved(info["handle"], lid, token, sha, dest, mime):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            frame = self._writer(
                info["name"],
                info["handle"],
                lid,
                self._package,
                dest,
                payload,
                cap,
                stop,
            )
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if not self._approved(info["handle"], lid, token, sha, dest, mime):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            failure = check_push_frame(frame, info, lid, self._package, dest, sha, len(payload))
            if failure is not None:
                return _reply("uncertain", "unknown", job_id=jid, error=failure, **base)
            receipt = {
                "purpose": "h4e-synthetic-atomic-import-v1",
                "schema_version": 1,
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "package_id": self._package,
                "destination_sha256": hashlib.sha256(dest.encode("ascii")).hexdigest(),
                "artifact_handle": token,
                "artifact_sha256": sha,
                "mime_type": mime,
                "bytes_written": len(payload),
                "synthetic_fixture_only": True,
            }
            content = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            report = self._artifacts.put(
                self._artifact_owner,
                content,
                mime_type="application/json",
                ttl_s=120,
            )
            reports.append(report["handle"])
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not self._approved(info["handle"], lid, token, sha, dest, mime):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            self._jobs.complete(
                self._owner,
                jid,
                _WORKER,
                running["generation"],
                info["handle"],
                authorized=True,
                result_digest=report["sha256"],
            )
            finished = True
            return _reply(
                "simulated",
                "imported_synthetic",
                job_id=jid,
                report_handle=report["handle"],
                report_sha256=report["sha256"],
                bytes_written=len(payload),
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
            AttributeError,
            ArtifactStoreError,
            JobStoreError,
            subprocess.SubprocessError,
        ):
            return _reply("uncertain", "unknown", job_id=jid, error="RUNNER_FAILED", **base)
        finally:
            with self._guard:
                self._active.pop(jid, None)
            if not finished:
                for item in reports:
                    try:
                        self._artifacts.revoke(self._artifact_owner, item)
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
        artifact_handle: str,
        artifact_sha256: str,
        destination_path: str,
        *,
        mime_type: str = "application/octet-stream",
        max_bytes: int = DEFAULT_PUSH_BYTES,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"plan", "push", "cancel"}:
            return _reply("blocked", error="INVALID_ACTION")
        target = approved_destination(self._package, destination_path)
        if target is None:
            return _reply("blocked", error="DESTINATION_DENIED")
        filename, expected_mime = target
        if not valid_request(
            lifecycle_job_id,
            artifact_handle,
            artifact_sha256,
            max_bytes,
            action,
            request_id,
            job_id,
        ):
            return _reply("blocked", error="INVALID_INPUT")
        if mime_type != expected_mime:
            return _reply("blocked", error="DESTINATION_DENIED")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        base = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lifecycle_job_id,
            "package_id": self._package,
            "filename": filename,
            "artifact_sha256": artifact_sha256,
            "mime_type": mime_type,
            "max_bytes": max_bytes,
        }
        if action == "plan":
            return _reply("planned", **base)
        assert request_id is not None
        if action == "cancel":
            assert job_id is not None
            return cancel_import(
                self._jobs,
                self._owner,
                info,
                lifecycle_job_id,
                artifact_handle,
                artifact_sha256,
                destination_path,
                filename,
                mime_type,
                max_bytes,
                request_id,
                job_id,
                self._package,
                self._signal_stop,
            )
        if self._writer is None or not self._approved(
            avd_handle,
            lifecycle_job_id,
            artifact_handle,
            artifact_sha256,
            destination_path,
            mime_type,
        ):
            return _reply("blocked", error="MUTATION_DISABLED", **base)
        if self._source(artifact_handle, artifact_sha256, mime_type, max_bytes) is None:
            return _reply("blocked", error="BAD_ARTIFACT", **base)
        if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
            return _reply("blocked", error="UNVERIFIED_TARGET", **base)
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", error="JOB_UNAVAILABLE", **base)
        if fd is None:
            return _reply("blocked", error="RECOVERY_REQUIRED", **base)
        try:
            return self._execute(
                info,
                lifecycle_job_id,
                artifact_handle,
                artifact_sha256,
                destination_path,
                filename,
                mime_type,
                max_bytes,
                request_id,
            )
        finally:
            os.close(fd)

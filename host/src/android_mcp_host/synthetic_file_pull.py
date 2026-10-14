"""H4.d exact approved synthetic app-export reader and private artifact receipts.

No real ADB read, arbitrary remote path, host output file, or physical target.
Only an out-of-band test harness can provide the synthetic reader and approval.
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
from android_mcp_host.file_pull_control import cancel_export
from android_mcp_host.file_pull_receipts import _reply, replay_export
from android_mcp_host.file_pull_support import (
    DEFAULT_PULL_BYTES,
    approved_source,
    transfer_digest,
    transfer_slot,
    valid_digest,
    valid_limit,
    valid_synthetic_package,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_WORKER = "h4d-private-synthetic-pull"
_TIMEOUT_S = 3.0


@dataclass(frozen=True, slots=True)
class FilePullApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    package_id: str
    remote_path: str
    expected_sha256: str
    purpose: str
    valid_until_epoch: float
    ttl_s: float


@dataclass(frozen=True, slots=True)
class FilePullFrame:
    payload: bytes
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    package_id: str
    remote_path: str
    mime_type: str
    declared_sha256: str
    regular: bool
    partial: bool
    synthetic: bool
    symlink: bool = False


Reader = Callable[[str, str, str, str, str, float, int, threading.Event], FilePullFrame]


def get_file_pull_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-synthetic-file-pull.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host private file pull schema")
    return value


class FilePullService:
    """One idempotent fixture export per exact owned AVD/lifecycle/source."""

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
        approval: FilePullApproval | None = None,
        fixture_reader: Reader | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or not valid_synthetic_package(package_id)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Untrusted private synthetic export configuration")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._package = package_id
        self._approval = approval
        self._fixture = fixture_reader
        self._clock = clock
        self._guard = threading.RLock()
        self._active: dict[str, threading.Event] = {}

    def _signal_stop(self, job_id: str) -> None:
        with self._guard:
            if job_id in self._active:
                self._active[job_id].set()

    def _approved(self, avd_handle: str, lid: str, path: str, expected: str) -> bool:
        grant = self._approval
        if grant is None:
            return False
        try:
            remaining = grant.valid_until_epoch - self._clock()
        except (TypeError, ValueError, ArithmeticError):
            return False
        return (
            grant.owner == self._owner
            and grant.avd_handle == avd_handle
            and grant.lifecycle_job_id == lid
            and grant.package_id == self._package
            and grant.remote_path == path
            and grant.expected_sha256 == expected
            and grant.purpose == "synthetic-app-export"
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

    def _execute(
        self,
        info: dict[str, Any],
        lid: str,
        remote: str,
        filename: str,
        request: str,
        expected_sha: str,
        mime: str,
        cap: int,
    ) -> dict[str, Any]:
        base = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lid,
            "package_id": self._package,
            "filename": filename,
            "mime": mime,
            "max_bytes": cap,
        }
        digest = transfer_digest(info, lid, remote, request, expected_sha, mime, cap)
        slot = transfer_slot(lid, remote)
        try:
            prior = self._jobs.lookup_request(self._owner, slot, digest, info["handle"])
            if prior is not None:
                return replay_export(
                    self._artifacts,
                    self._artifact_owner,
                    prior,
                    name=info["name"],
                    avd_handle=info["handle"],
                    lifecycle_id=lid,
                    package=self._package,
                    remote_path=remote,
                    filename=filename,
                    expected_sha=expected_sha,
                    mime=mime,
                    cap=cap,
                )
            if any(
                item["job_id"] != lid
                and item["state"] in {"prepared", "queued", "running", "uncertain"}
                for item in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", error="RECOVERY_REQUIRED", **base)
            job = self._jobs.prepare(
                self._owner, slot, digest, identity=info["handle"], authorized=True
            )
            jid = str(job["job_id"])
            self._jobs.queue(self._owner, jid, identity=info["handle"], authorized=True)
            running = self._jobs.claim(self._owner, jid, _WORKER, info["handle"], authorized=True)
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
                self._package,
                remote,
                _TIMEOUT_S,
                cap,
                stop,
            )
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if not self._approved(info["handle"], lid, remote, expected_sha):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
            if (
                type(frame) is not FilePullFrame
                or frame.avd_name != info["name"]
                or frame.avd_handle != info["handle"]
                or frame.lifecycle_job_id != lid
                or frame.package_id != self._package
                or frame.remote_path != remote
                or frame.mime_type != mime
                or frame.synthetic is not True
                or type(frame.regular) is not bool
                or type(frame.symlink) is not bool
                or type(frame.partial) is not bool
            ):
                response = self._finish_bad(info, jid, running["generation"], "BAD_FRAME", base)
                finished = True
                return response
            if not frame.regular or frame.symlink:
                response = self._finish_bad(
                    info, jid, running["generation"], "SYMLINK_DENIED", base
                )
                finished = True
                return response
            if frame.partial:
                response = self._finish_bad(
                    info, jid, running["generation"], "PARTIAL_TRANSFER", base
                )
                finished = True
                return response
            if type(frame.payload) is not bytes or not 1 <= len(frame.payload) <= cap:
                response = self._finish_bad(
                    info, jid, running["generation"], "TRANSFER_TOO_LARGE", base
                )
                finished = True
                return response
            actual = hashlib.sha256(frame.payload).hexdigest()
            if frame.declared_sha256 != expected_sha or actual != expected_sha:
                response = self._finish_bad(
                    info, jid, running["generation"], "CHECKSUM_MISMATCH", base
                )
                finished = True
                return response

            artifact = self._artifacts.put(
                self._artifact_owner,
                frame.payload,
                mime_type=mime,
                ttl_s=self._approval.ttl_s,
            )
            handles.append(artifact["handle"])
            receipt = {
                "purpose": "h4d-synthetic-private-file-pull-v1",
                "schema_version": 1,
                "job_id": jid,
                "avd_handle": info["handle"],
                "lifecycle_job_id": lid,
                "package_id": self._package,
                "source_path_sha256": hashlib.sha256(remote.encode("ascii")).hexdigest(),
                "filename": filename,
                "mime_type": mime,
                "sha256": actual,
                "artifact_handle": artifact["handle"],
                "synthetic_fixture_only": True,
            }
            encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
            proof = self._artifacts.put(
                self._artifact_owner,
                encoded,
                mime_type="application/json",
                ttl_s=self._approval.ttl_s,
            )
            handles.append(proof["handle"])
            if stop.is_set():
                return _reply("uncertain", "unknown", job_id=jid, error="CANCELLED", **base)
            if not verified_fake_target(self._lifecycle, info, lid):
                return _reply("uncertain", "unknown", job_id=jid, error="UNVERIFIED_TARGET", **base)
            if not self._approved(info["handle"], lid, remote, expected_sha):
                return _reply("uncertain", "unknown", job_id=jid, error="CONSENT_REQUIRED", **base)
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
                "pulled_synthetic",
                job_id=jid,
                artifact_handle=artifact["handle"],
                receipt_handle=proof["handle"],
                sha256=actual,
                size_bytes=len(frame.payload),
                **base,
            )
        except subprocess.TimeoutExpired:
            return _reply("uncertain", "unknown", job_id=jid, error="TIMEOUT", **base)
        except (
            OSError,
            ValueError,
            RuntimeError,
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
                for handle in handles:
                    try:
                        self._artifacts.revoke(self._artifact_owner, handle)
                    except ArtifactStoreError:
                        pass
                try:
                    self._jobs.cancel(self._owner, jid, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        remote_path: str,
        *,
        expected_sha256: str | None = None,
        mime_type: str = "application/octet-stream",
        max_bytes: int = DEFAULT_PULL_BYTES,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"plan", "pull", "cancel"}:
            return _reply("blocked", error="INVALID_ACTION")
        source = approved_source(self._package, remote_path)
        if source is None:
            return _reply("blocked", error="SOURCE_DENIED")
        filename, required_mime = source
        if (
            not isinstance(lifecycle_job_id, str)
            or _JOB.fullmatch(lifecycle_job_id) is None
            or not valid_limit(max_bytes)
            or (
                action == "pull"
                and (
                    not valid_digest(expected_sha256)
                    or not isinstance(request_id, str)
                    or _REQUEST.fullmatch(request_id) is None
                )
            )
            or (expected_sha256 is not None and not valid_digest(expected_sha256))
            or (
                action == "cancel"
                and (not isinstance(job_id, str) or _JOB.fullmatch(job_id) is None)
            )
        ):
            return _reply("blocked", error="INVALID_INPUT")
        if action != "plan" and mime_type != required_mime:
            return _reply("blocked", error="SOURCE_DENIED")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        base = {
            "name": info["name"],
            "handle": info["handle"],
            "lifecycle_id": lifecycle_job_id,
            "package_id": self._package,
            "filename": filename,
            "mime": required_mime,
            "max_bytes": max_bytes,
        }
        if action == "plan":
            return _reply("planned", **base)
        assert isinstance(expected_sha256, str) and request_id is not None
        if action == "cancel":
            assert job_id is not None
            return cancel_export(
                self._jobs,
                self._owner,
                info,
                lifecycle_job_id,
                remote_path,
                filename,
                request_id,
                expected_sha256,
                required_mime,
                max_bytes,
                job_id,
                self._signal_stop,
            )
        if not self._approved(avd_handle, lifecycle_job_id, remote_path, expected_sha256):
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
            return self._execute(
                info,
                lifecycle_job_id,
                remote_path,
                filename,
                request_id,
                expected_sha256,
                required_mime,
                max_bytes,
            )
        finally:
            os.close(fd)

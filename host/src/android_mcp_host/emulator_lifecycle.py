"""H3.c inert real-emulator policy with a bounded synthetic child backend.

The public production composition never injects a real emulator backend.
Only a digest-pinned synthetic fixture can start a subprocess in tests.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.synthetic_emulator_backend import (
    SyntheticEmulatorBackend,
    SyntheticEmulatorError,
)

_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_SERIAL = re.compile(r"emulator-([0-9]{4,5})\Z", re.ASCII)
_WORKER = "h3c-synthetic-emulator-worker"
_ERRORS = {
    "NOT_OWNED": "Exact private disposable AVD ownership is not confirmed",
    "INVALID_ACTION": "Emulator lifecycle action is unsupported",
    "INVALID_REQUEST": "Lifecycle request identifier is invalid",
    "INVALID_JOB": "Lifecycle job is unavailable",
    "EXECUTION_DISABLED": "Real emulator execution remains disabled",
    "RECOVERY_REQUIRED": "Prior emulator lifecycle state needs trusted reconciliation",
    "IDEMPOTENCY_CONFLICT": "Request identity was reused with a different plan",
    "JOB_UNAVAILABLE": "Durable emulator job is unavailable",
    "SPAWN_FAILED": "Synthetic emulator child could not be started",
    "READINESS_REJECTED": "Synthetic emulator identity or readiness was not confirmed",
    "READINESS_TIMEOUT": "Synthetic emulator readiness timed out",
    "READINESS_LIMIT": "Synthetic readiness exceeded the bounded limit",
    "PROCESS_EXITED": "Synthetic emulator child exited prematurely",
    "STOP_UNCONFIRMED": "Synthetic process stop could not be confirmed",
}


def get_emulator_lifecycle_schema() -> dict[str, Any]:
    result: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-emulator-lifecycle.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(result, dict):
        raise ValueError("Invalid packaged Host emulator lifecycle schema")
    return result


def _result(
    status: str,
    state: str,
    metadata: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
    confirmed: bool = False,
    synthetic_enabled: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "lifecycle_state": state,
        "job_id": job_id,
        "name": metadata["name"] if metadata else None,
        "handle": metadata["handle"] if metadata else None,
        "api": metadata["api"] if metadata else None,
        "abi": metadata["abi"] if metadata else None,
        "artifact_sha256": metadata["artifact_sha256"] if metadata else None,
        "target": "disposable_emulator_only",
        "process_confirmed": confirmed,
        "synthetic_execution_enabled": synthetic_enabled,
        "real_emulator_execution_enabled": False,
        "physical_device_writes_enabled": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


@dataclass(slots=True)
class _Session:
    process: subprocess.Popen[bytes]
    name: str
    handle: str
    generation: int


class EmulatorLifecycle:
    """Status and fake-only lifespan; no default real QEMU execution."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        jobs: DurableJobStore,
        *,
        owner: str,
        backend: SyntheticEmulatorBackend | None = None,
        readiness_timeout_s: float = 2.0,
    ) -> None:
        if not jobs.validate_owner(owner) or owner != provisioner.trusted_owner:
            raise ValueError("Invalid dedicated lifecycle owner")
        if type(readiness_timeout_s) not in (float, int) or not 0 < readiness_timeout_s <= 5.0:
            raise ValueError("Invalid finite synthetic readiness deadline")
        if backend is not None and not isinstance(backend, SyntheticEmulatorBackend):
            raise ValueError("Only pinned synthetic backend is permitted")
        self.provisioner = provisioner
        self._jobs = jobs
        self._owner = owner
        self._backend = backend
        self._timeout = readiness_timeout_s
        self._guard = threading.RLock()
        self._sessions: dict[str, _Session] = {}

    @staticmethod
    def _digest(info: dict[str, Any]) -> str:
        plan = {
            "lifecycle": "h3c-synthetic-start-v1",
            "handle": info["handle"],
            "api": info["api"],
            "abi": info["abi"],
            "artifact_sha256": info["artifact_sha256"],
        }
        return hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()

    @staticmethod
    def _verified_ready(
        report: dict[str, Any], info: dict[str, Any], process: subprocess.Popen[bytes]
    ) -> bool:
        if set(report) != {"qemu", "avd", "api", "abi", "boot_completed", "serial", "pid"}:
            return False
        serial = report.get("serial")
        matched = _SERIAL.fullmatch(serial) if isinstance(serial, str) else None
        return (
            report.get("qemu") is True
            and report.get("boot_completed") is True
            and report.get("avd") == info["name"]
            and type(report.get("api")) is int
            and report["api"] == info["api"]
            and report.get("abi") == info["abi"]
            and type(report.get("pid")) is int
            and report["pid"] == process.pid
            and matched is not None
            and 5554 <= int(matched.group(1)) <= 5680
            and int(matched.group(1)) % 2 == 0
        )

    def _existing(self, info: dict[str, Any], job_id: str) -> dict[str, Any]:
        try:
            response = self._jobs.status(self._owner, job_id)
        except JobStoreError:
            return _result("uncertain", "uncertain", info, job_id=job_id, error="JOB_UNAVAILABLE")
        if response["status"] != "ok" or response["job"]["plan_digest"] != self._digest(info):
            return _result("not_found", "not_found", info, error="INVALID_JOB")
        state = response["job"]["state"]
        if state == "succeeded":
            return _result("ok", "stopped", info, job_id=job_id)
        if state == "failed":
            return _result("failed", "failed", info, job_id=job_id)
        if state in {"cancelled", "uncertain"}:
            return _result("uncertain", "uncertain", info, job_id=job_id)
        session = self._sessions.get(job_id)
        if session is not None and self._backend is not None:
            try:
                alive = self._backend.is_running(session.process)
            except (OSError, ValueError, RuntimeError):
                alive = False
            if alive:
                return _result(
                    "ok",
                    "running",
                    info,
                    job_id=job_id,
                    confirmed=True,
                    synthetic_enabled=True,
                )
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
        return _result("uncertain", "uncertain", info, job_id=job_id)

    def _start(self, info: dict[str, Any], request_id: str) -> dict[str, Any]:
        if self._backend is None:
            return _result("blocked", "blocked", info, error="EXECUTION_DISABLED")
        digest = self._digest(info)
        try:
            prior = self._jobs.lookup_request(self._owner, request_id, digest, info["handle"])
            if prior is not None:
                return self._existing(info, str(prior["job_id"]))
            if any(
                record["state"] in {"prepared", "queued", "running", "uncertain"}
                for record in self._jobs.list_status(self._owner)
            ):
                return _result("blocked", "blocked", info, error="RECOVERY_REQUIRED")
            record = self._jobs.prepare(
                self._owner,
                request_id,
                digest,
                identity=info["handle"],
                authorized=True,
            )
            job_id = str(record["job_id"])
            self._jobs.queue(self._owner, job_id, identity=info["handle"], authorized=True)
            running = self._jobs.claim(
                self._owner, job_id, _WORKER, info["handle"], authorized=True
            )
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return _result("blocked", "blocked", info, error=code)
        try:
            process, report = self._backend.launch(
                info["name"], self.provisioner.private_root, self._timeout
            )
        except (
            SyntheticEmulatorError,
            OSError,
            ValueError,
            RuntimeError,
            TypeError,
            subprocess.SubprocessError,
        ) as error:
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
            code = (
                error.code
                if isinstance(error, SyntheticEmulatorError) and error.code in _ERRORS
                else "SPAWN_FAILED"
            )
            return _result("uncertain", "uncertain", info, job_id=job_id, error=code)
        try:
            ready = isinstance(report, dict) and self._verified_ready(report, info, process)
        except (TypeError, ValueError, KeyError, AttributeError):
            ready = False
        if not ready:
            try:
                terminated = self._backend.stop(process)
            except (OSError, ValueError, RuntimeError):
                terminated = False
            if terminated:
                try:
                    self._jobs.complete(
                        self._owner,
                        job_id,
                        _WORKER,
                        running["generation"],
                        info["handle"],
                        authorized=True,
                        failure_code="READINESS_REJECTED",
                    )
                except JobStoreError:
                    terminated = False
            if not terminated:
                try:
                    self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass
            return _result(
                "failed" if terminated else "uncertain",
                "failed" if terminated else "uncertain",
                info,
                job_id=job_id,
                error="READINESS_REJECTED",
            )
        self._sessions[job_id] = _Session(
            process, info["name"], info["handle"], running["generation"]
        )
        return _result(
            "ok",
            "running",
            info,
            job_id=job_id,
            confirmed=True,
            synthetic_enabled=True,
        )

    def _stop(self, info: dict[str, Any], job_id: str) -> dict[str, Any]:
        current = self._existing(info, job_id)
        if current["lifecycle_state"] != "running":
            return current
        session = self._sessions.get(job_id)
        if session is None or self._backend is None:
            return _result("uncertain", "uncertain", info, job_id=job_id)
        try:
            terminated = self._backend.stop(session.process)
        except (OSError, ValueError, RuntimeError):
            terminated = False
        if not terminated:
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
            return _result("uncertain", "uncertain", info, job_id=job_id, error="STOP_UNCONFIRMED")
        self._sessions.pop(job_id, None)
        completed_digest = hashlib.sha256(
            ("synthetic-stopped:" + job_id).encode("ascii")
        ).hexdigest()
        try:
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                session.generation,
                info["handle"],
                authorized=True,
                result_digest=completed_digest,
            )
        except JobStoreError:
            return _result("uncertain", "uncertain", info, job_id=job_id)
        return _result("ok", "stopped", info, job_id=job_id)

    def run(
        self,
        action: str,
        name: str,
        handle: str,
        *,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """One typed lifecycle Tool; model cannot select a PID or executable."""
        if action not in {"plan", "start", "stop", "status"}:
            return _result("blocked", "blocked", error="INVALID_ACTION")
        info = self.provisioner.verify_owned(name, handle)
        if info is None:
            return _result("blocked", "blocked", error="NOT_OWNED")
        if action == "plan":
            return _result("planned", "planned", info)
        if action == "start" and (
            not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None
        ):
            return _result("blocked", "blocked", info, error="INVALID_REQUEST")
        with self._guard:
            if action == "start":
                assert request_id is not None
                return self._start(info, request_id)
            if not isinstance(job_id, str):
                return _result("not_found", "not_found", info, error="INVALID_JOB")
            if action == "stop" and self._backend is None:
                return _result("blocked", "blocked", info, error="EXECUTION_DISABLED")
            return self._stop(info, job_id) if action == "stop" else self._existing(info, job_id)

    def shutdown(self) -> int:
        """Best-effort controlled fixture cleanup; never signals a caller PID."""
        with self._guard:
            sessions = list(self._sessions.items())
            self._sessions.clear()
            for job_id, session in sessions:
                if self._backend is not None:
                    try:
                        self._backend.stop(session.process)
                    except (OSError, ValueError, RuntimeError):
                        pass
                try:
                    self._jobs.cancel(self._owner, job_id, identity=session.handle, authorized=True)
                except JobStoreError:
                    pass
            return len(sessions)

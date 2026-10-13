"""H3.e private, durable synthetic-only instrumentation job conformance.

The public Host CLI never injects an execution backend: no ADB, APK install,
real emulator mutation, or arbitrary subprocess argv is enabled here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any

from android_mcp_host.archive_validation import ArchiveValidationError, inspect_zip
from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.command_runner import RunResult
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_instrumentation_support import (
    MAX_OUTPUT_BYTES,
    claim_fixture_lock,
    parse_fixture_result,
    valid_component,
    valid_digest,
)
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

APK = "application/vnd.android.package-archive"
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
MAX_TIMEOUT_S = 10.0
_WORKER = "h3e-synthetic-instrumentation-worker"
Runner = Callable[[Sequence[str], float, int], RunResult]
_ERRORS = {
    "INVALID_ACTION": "Instrumentation action is unsupported",
    "INVALID_INPUT": "Instrumentation request has invalid bounded fields",
    "NOT_OWNED": "Target AVD is not owned by the Host",
    "UNVERIFIED_EMULATOR": "Running synthetic target is not independently confirmed",
    "BAD_ARTIFACT": "Private test APK is unavailable or invalid",
    "EXECUTION_DISABLED": "Real instrumentation execution remains disabled",
    "RECOVERY_REQUIRED": "Earlier test job requires trusted reconciliation",
    "IDEMPOTENCY_CONFLICT": "Request does not match its original test plan",
    "JOB_UNAVAILABLE": "Durable instrumentation job is unavailable",
    "TEST_FAILED": "Synthetic test runner reported failed cases",
    "OUTPUT_INVALID": "Synthetic runner result is malformed or truncated",
    "TIMEOUT": "Test execution outcome is uncertain after timeout",
    "RUNNER_FAILED": "Synthetic test runner failed",
    "ARTIFACT_FAILED": "Private test report could not be stored",
}


def get_instrumentation_schema() -> dict[str, Any]:
    result: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-emulator-instrumentation.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(result, dict):
        raise ValueError("Invalid packaged Host instrumentation schema")
    return result


def _reply(
    status: str,
    state: str | None,
    *,
    avd_name: str | None = None,
    avd_handle: str | None = None,
    apk_sha256: str | None = None,
    job_id: str | None = None,
    report_handle: str | None = None,
    report_sha256: str | None = None,
    passed: int | None = None,
    failed: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "state": state,
        "avd_name": avd_name,
        "avd_handle": avd_handle,
        "apk_sha256": apk_sha256,
        "job_id": job_id,
        "report_handle": report_handle,
        "report_sha256": report_sha256,
        "passed": passed,
        "failed": failed,
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_instrumentation_enabled": False,
        "physical_device_writes_enabled": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


class InstrumentationJobs:
    """Fixed synthetic argv and persisted one-claim test report receipts."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        fixture_runner: Runner | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Invalid trusted synthetic instrumentation owner")
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= MAX_TIMEOUT_S:
            raise ValueError("Invalid finite test execution deadline")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._runner = fixture_runner
        self._timeout = float(timeout_s)

    @staticmethod
    def _digest(
        info: dict[str, Any],
        lifecycle_job: str,
        artifact_handle: str,
        apk_sha256: str,
        component: str,
    ) -> str:
        plan = {
            "protocol": "h3e-synthetic-only-v1",
            "avd_handle": info["handle"],
            "image_sha256": info["artifact_sha256"],
            "target_job_id": lifecycle_job,
            "apk_handle": artifact_handle,
            "apk_sha256": apk_sha256,
            "component": component,
        }
        return hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()

    def _apk(self, handle: str, expected_sha256: str) -> bool:
        meta = self._artifacts.public_metadata(self._artifact_owner, handle)
        if meta["status"] != "ok":
            return False
        record = meta["artifact"]
        if record["mime_type"] != APK or record["sha256"] != expected_sha256:
            return False
        try:
            data = self._artifacts.read(self._artifact_owner, handle)
            inspect_zip(data, APK)
            return hashlib.sha256(data).hexdigest() == expected_sha256
        except (ArtifactStoreError, ArchiveValidationError, OSError):
            return False

    def _status(
        self,
        info: dict[str, Any],
        lifecycle_job_id: str,
    ) -> bool:
        try:
            result = self._lifecycle.run(
                "status", info["name"], info["handle"], job_id=lifecycle_job_id
            )
        except (JobStoreError, OSError, ValueError, RuntimeError):
            return False
        return (
            result["status"] == "ok"
            and result["lifecycle_state"] == "running"
            and result["process_confirmed"] is True
            and result["synthetic_execution_enabled"] is True
            and result["real_emulator_execution_enabled"] is False
            and result["physical_device_writes_enabled"] is False
        )

    def _existing(
        self,
        job: dict[str, Any],
        info: dict[str, Any],
        apk_sha256: str,
        component: str,
    ) -> dict[str, Any]:
        state = str(job["state"])
        result = _reply(
            "ok" if state == "succeeded" else ("failed" if state == "failed" else "uncertain"),
            state,
            avd_name=info["name"],
            avd_handle=info["handle"],
            apk_sha256=apk_sha256,
            job_id=str(job["job_id"]),
            report_sha256=job.get("result_digest"),
        )
        digest = job.get("result_digest")
        if state != "succeeded" or not isinstance(digest, str):
            return result
        # Recover a report only from the private artifact owner and exact hash.
        try:
            for record in self._artifacts.list_metadata(self._artifact_owner):
                if record["sha256"] != digest or record["mime_type"] != "application/json":
                    continue
                data = self._artifacts.read(self._artifact_owner, record["handle"])
                parsed = json.loads(data)
                if (
                    not isinstance(parsed, dict)
                    or parsed.get("job_id") != job["job_id"]
                    or parsed.get("state") != "succeeded"
                    or parsed.get("target_avd_handle") != info["handle"]
                    or parsed.get("apk_sha256") != apk_sha256
                    or parsed.get("component") != component
                    or parsed.get("synthetic_fixture_only") is not True
                ):
                    continue
                result["report_handle"] = record["handle"]
                result["passed"] = parsed["passed"]
                result["failed"] = parsed["failed"]
                break
        except (ArtifactStoreError, KeyError, TypeError, ValueError, OSError):
            pass
        return result

    def _finish(
        self,
        info: dict[str, Any],
        job_id: str,
        generation: int,
        apk_sha256: str,
        component: str,
        outcome: RunResult,
    ) -> dict[str, Any]:
        if outcome.truncated:
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                generation,
                info["handle"],
                authorized=True,
                failure_code="OUTPUT_INVALID",
            )
            return _reply("failed", "failed", job_id=job_id, error="OUTPUT_INVALID")
        summary = parse_fixture_result(outcome.stdout)
        if summary is None:
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                generation,
                info["handle"],
                authorized=True,
                failure_code="OUTPUT_INVALID",
            )
            return _reply("failed", "failed", job_id=job_id, error="OUTPUT_INVALID")
        passed, failed = summary["passed"], summary["failed"]
        succeeded = outcome.returncode == 0 and failed == 0 and not outcome.stderr
        state = "succeeded" if succeeded else "failed"
        private_report = {
            "schema_version": 1,
            "runtime": "host",
            "job_id": job_id,
            "state": state,
            "case_total": summary["total"],
            "passed": passed,
            "failed": failed,
            "target_avd_handle": info["handle"],
            "apk_sha256": apk_sha256,
            "component": component,
            "synthetic_fixture_only": True,
        }
        encoded = json.dumps(private_report, sort_keys=True, separators=(",", ":")).encode()
        artifact = self._artifacts.put(self._artifact_owner, encoded, mime_type="application/json")
        digest = hashlib.sha256(encoded).hexdigest()
        self._jobs.complete(
            self._owner,
            job_id,
            _WORKER,
            generation,
            info["handle"],
            authorized=True,
            result_digest=digest if succeeded else None,
            failure_code="TEST_FAILED" if not succeeded else None,
        )
        return _reply(
            "ok" if succeeded else "failed",
            state,
            avd_name=info["name"],
            avd_handle=info["handle"],
            apk_sha256=apk_sha256,
            job_id=job_id,
            report_handle=artifact["handle"],
            report_sha256=digest,
            passed=passed,
            failed=failed,
            error=None if succeeded else "TEST_FAILED",
        )

    def _run(
        self,
        info: dict[str, Any],
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        component: str,
        request_id: str,
    ) -> dict[str, Any]:
        if self._runner is None:
            return _reply("blocked", "blocked", error="EXECUTION_DISABLED")
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", "blocked", error="JOB_UNAVAILABLE")
        if fd is None:
            return _reply("blocked", "blocked", error="RECOVERY_REQUIRED")
        try:
            return self._run_locked(
                info, lifecycle_job_id, apk_handle, apk_sha256, component, request_id
            )
        finally:
            os.close(fd)

    def _run_locked(
        self,
        info: dict[str, Any],
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        component: str,
        request_id: str,
    ) -> dict[str, Any]:
        if self._runner is None:
            return _reply("blocked", "blocked", error="EXECUTION_DISABLED")
        if not self._status(info, lifecycle_job_id):
            return _reply("blocked", "blocked", error="UNVERIFIED_EMULATOR")
        digest = self._digest(info, lifecycle_job_id, apk_handle, apk_sha256, component)
        try:
            previous = self._jobs.lookup_request(self._owner, request_id, digest, info["handle"])
            if previous is not None:
                return self._existing(previous, info, apk_sha256, component)
            if any(
                row["state"] in {"prepared", "queued", "running", "uncertain"}
                and row["job_id"] != lifecycle_job_id
                for row in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", "blocked", error="RECOVERY_REQUIRED")
            prepared = self._jobs.prepare(
                self._owner, request_id, digest, identity=info["handle"], authorized=True
            )
            job_id = str(prepared["job_id"])
            self._jobs.queue(self._owner, job_id, identity=info["handle"], authorized=True)
            claimed = self._jobs.claim(
                self._owner,
                job_id,
                _WORKER,
                info["handle"],
                authorized=True,
            )
        except JobStoreError as error:
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else ("JOB_UNAVAILABLE")
            )
            return _reply("blocked", "blocked", error=code)
        argv = [
            "fixture-instrumentation",
            "--avd",
            info["name"],
            "--lifecycle-job",
            lifecycle_job_id,
            "--apk-sha256",
            apk_sha256,
            "--component",
            component,
        ]
        try:
            output = self._runner(argv, self._timeout, MAX_OUTPUT_BYTES)
            if not self._status(info, lifecycle_job_id):
                # The exact synthetic child could exit during fixture execution.
                # Never publish success from a stale pre-run readiness check.
                try:
                    self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass
                return _reply(
                    "uncertain",
                    "uncertain",
                    job_id=job_id,
                    error="UNVERIFIED_EMULATOR",
                )
            return self._finish(info, job_id, claimed["generation"], apk_sha256, component, output)
        except subprocess.TimeoutExpired:
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
            return _reply("uncertain", "uncertain", job_id=job_id, error="TIMEOUT")
        except (
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            JobStoreError,
            ArtifactStoreError,
        ):
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
            return _reply("uncertain", "uncertain", job_id=job_id, error="RUNNER_FAILED")

    def _cancel(
        self,
        info: dict[str, Any],
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        component: str,
        request_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        digest = self._digest(info, lifecycle_job_id, apk_handle, apk_sha256, component)
        try:
            previous = self._jobs.lookup_request(self._owner, request_id, digest, info["handle"])
            if previous is None or previous["job_id"] != job_id:
                return _reply("blocked", "blocked", error="JOB_UNAVAILABLE")
            if previous["state"] in {"succeeded", "failed", "cancelled"}:
                return _reply("blocked", "blocked", error="JOB_UNAVAILABLE")
            self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
        except JobStoreError as error:
            if error.code == "IDEMPOTENCY_CONFLICT":
                return _reply("blocked", "blocked", error="IDEMPOTENCY_CONFLICT")
            return _reply("uncertain", "uncertain", job_id=job_id, error="JOB_UNAVAILABLE")
        return _reply("uncertain", "uncertain", job_id=job_id)

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        component: str,
        *,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Never execute an Android real instrument process through MCP."""
        if action not in {"plan", "run", "cancel"}:
            return _reply("blocked", "blocked", error="INVALID_ACTION")
        if (
            not valid_component(component)
            or not valid_digest(apk_sha256)
            or not isinstance(lifecycle_job_id, str)
            or _JOB.fullmatch(lifecycle_job_id) is None
        ):
            return _reply("blocked", "blocked", error="INVALID_INPUT")
        if action in {"run", "cancel"} and (
            not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None
        ):
            return _reply("blocked", "blocked", error="INVALID_INPUT")
        if action == "cancel" and (not isinstance(job_id, str) or _JOB.fullmatch(job_id) is None):
            return _reply("blocked", "blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", "blocked", error="NOT_OWNED")
        if not self._apk(apk_handle, apk_sha256):
            return _reply("blocked", "blocked", error="BAD_ARTIFACT")
        if action == "plan":
            return _reply(
                "planned",
                "planned",
                avd_name=info["name"],
                avd_handle=info["handle"],
                apk_sha256=apk_sha256,
            )
        assert request_id is not None
        if action == "cancel":
            assert job_id is not None
            return self._cancel(
                info, lifecycle_job_id, apk_handle, apk_sha256, component, request_id, job_id
            )
        return self._run(info, lifecycle_job_id, apk_handle, apk_sha256, component, request_id)

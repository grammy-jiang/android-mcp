"""Opt-in, pinned local Gradle jobs with durable single-claim metadata.

Only trusted Host composition can configure build root, revision, wrapper,
job owner and private artifact store. The MCP caller chooses one closed action
and an idempotency key, never a shell, arbitrary task, path or target device.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.android_build_preflight import TASKS, AndroidBuildPreflight
from android_mcp_host.archive_validation import ArchiveValidationError, inspect_zip
from android_mcp_host.command_runner import RunResult, bounded_run
from android_mcp_host.controlled_build_support import checkout_lock, output_stamp, safe_build_file
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError, _private_directory

_SHA = re.compile(r"[0-9a-f]{40,64}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MAX_OUTPUT_BYTES = 65536
MAX_RUNTIME_SECONDS = 120.0
MAX_APK_BYTES = 8 * 1024 * 1024
_WORKER = "host-gradle-worker-v1"
_APK_MIME = "application/vnd.android.package-archive"
_ENV = {
    "PATH": "/opt/homebrew/opt/openjdk@17/bin:/usr/bin:/bin:/opt/homebrew/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "CI": "true",
    "GRADLE_OPTS": "-Dorg.gradle.daemon=false",
}
Runner = Callable[[Sequence[str], float, int, Path], RunResult]
_MESSAGES = {
    "NOT_APPROVED": "Build prerequisites are unavailable",
    "INVALID_ACTION": "Build action is not permitted",
    "INVALID_REQUEST": "Request identifier is invalid",
    "IDEMPOTENCY_CONFLICT": "Request was previously used for another plan",
    "JOB_UNAVAILABLE": "Build job is unavailable",
    "BUILD_FAILED": "Offline Gradle command did not succeed",
    "OUTPUT_INVALID": "Expected debug APK is unavailable or invalid",
    "OUTPUT_LIMIT": "Build output exceeded the finite limit",
    "TIMEOUT": "Build outcome is uncertain after timeout",
    "RUNNER_FAILED": "Build runner failed",
    "ARTIFACT_FAILED": "Private build artifact could not be saved",
    "BUILD_BUSY": "Another build is using the approved checkout",
    "RECOVERY_REQUIRED": "A previous worker needs trusted reconciliation",
}


def get_build_job_schema() -> dict[str, Any]:
    """Return the versioned metadata-only wire schema from the wheel."""
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-controlled-build-job.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host controlled build schema")
    return value


def _run_gradle(argv: Sequence[str], seconds: float, limit: int, cwd: Path) -> RunResult:
    """Execute only preconstructed positional argv without a user shell."""
    return bounded_run(argv, seconds, limit, cwd=cwd, env=_ENV)


def _result(
    status: str,
    state: str | None,
    job_id: str | None = None,
    *,
    report_handle: str | None = None,
    apk_handle: str | None = None,
    result_sha256: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "state": state,
        "job_id": job_id,
        "report_handle": report_handle,
        "apk_handle": apk_handle,
        "result_sha256": result_sha256,
        "errors": [{"code": error, "message": _MESSAGES[error]}] if error else [],
        "device_mutation_enabled": False,
    }


class ControlledBuildJobs:
    """Pinned, finite Host offline build execution, with no target device."""

    def __init__(
        self,
        *,
        preflight: AndroidBuildPreflight,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        root: Path,
        approved_revision: str,
        wrapper_sha256: str,
        owner: str,
        artifact_owner: str,
        runner: Runner | None = None,
        timeout_s: float = 90.0,
    ) -> None:
        if (
            not isinstance(root, Path)
            or not root.is_absolute()
            or ".." in root.parts
            or len(str(root)) > 1024
            or not isinstance(approved_revision, str)
            or _SHA.fullmatch(approved_revision) is None
            or not isinstance(wrapper_sha256, str)
            or _DIGEST.fullmatch(wrapper_sha256) is None
            or not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
        ):
            raise ValueError("Invalid trusted Host build configuration")
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= MAX_RUNTIME_SECONDS:
            raise ValueError("Invalid Host build execution deadline")
        self._preflight = preflight
        self._jobs = jobs
        self._artifacts = artifacts
        self._root = root
        self._revision = approved_revision
        self._wrapper = wrapper_sha256
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._runner = runner if runner is not None else self._run_private_gradle
        self._timeout = float(timeout_s)

    def _run_private_gradle(
        self, argv: Sequence[str], seconds: float, limit: int, cwd: Path
    ) -> RunResult:
        """Isolate Gradle caches and HOME from the operator's user profile."""
        digest = hashlib.sha256(str(self._root).encode("utf-8")).hexdigest()[:24]
        gradle_home = self._jobs.private_root / ("gradle-home-" + digest)
        _private_directory(gradle_home)
        env = {**_ENV, "HOME": str(gradle_home), "GRADLE_USER_HOME": str(gradle_home)}
        return bounded_run(argv, seconds, limit, cwd=cwd, env=env)

    def _project_lock(self) -> int | None:
        return checkout_lock(self._jobs.private_root, self._root)

    def _output_stamp(self) -> tuple[int, ...] | None:
        return output_stamp(self._root)

    def _replay(self, state: str, job_id: str, digest: str | None) -> dict[str, Any]:
        status = {
            "succeeded": "ok",
            "failed": "failed",
            "cancelled": "failed",
            "uncertain": "uncertain",
        }.get(state, "in_progress")
        result = _result(status, state, job_id, result_sha256=digest)
        if state != "succeeded" or digest is None:
            return result
        # The job ledger stores only a digest; retrieve the matching private
        # structured report by digest. Missing/expired records are never
        # recreated or used to trigger a second build.
        try:
            for candidate in self._artifacts.list_metadata(self._artifact_owner):
                if candidate["sha256"] != digest:
                    continue
                handle = candidate["handle"]
                raw = self._artifacts.read(self._artifact_owner, handle)
                record = json.loads(raw)
                if record.get("job_id") != job_id or record.get("state") != "succeeded":
                    continue
                result["report_handle"] = handle
                handle_apk = record.get("apk_handle")
                if isinstance(handle_apk, str):
                    if (
                        self._artifacts.public_metadata(self._artifact_owner, handle_apk)["status"]
                        == "ok"
                    ):
                        result["apk_handle"] = handle_apk
                break
        except (ArtifactStoreError, OSError, ValueError, TypeError, KeyError):
            pass
        return result

    def _plan_digest(self, action: str, variant: str) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "action": action,
                    "variant": variant,
                    "revision": self._revision,
                    "wrapper": self._wrapper,
                },
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()

    def _approved(self, action: str, variant: str) -> bool:
        """Revalidate approved preflight *and* executable bytes before any claim."""
        try:
            if any(part.is_symlink() for part in (self._root, *self._root.parents)):
                return False
            if not self._root.is_dir() or self._root.stat().st_uid != os.getuid():
                return False
            check = self._preflight.plan(action, variant)
            if not isinstance(check, dict) or any(
                (
                    check.get("status") != "planned",
                    check.get("action") != action,
                    check.get("variant") != variant,
                    check.get("project_root") != str(self._root),
                    check.get("expected_revision") != self._revision,
                    check.get("observed_revision") != self._revision,
                    check.get("wrapper_sha256") != self._wrapper,
                    check.get("dirty") is not False,
                    check.get("execution_enabled") is not False,
                    check.get("tasks") != list(TASKS[action]),
                )
            ):
                return False
            gradlew = self._root / "android" / "gradlew"
            wrapper = self._root / "android" / "gradle/wrapper/gradle-wrapper.jar"
            for fixed in (
                self._root / "android",
                self._root / "android" / "gradle",
                self._root / "android" / "gradle/wrapper",
                gradlew,
                wrapper,
            ):
                if fixed.is_symlink():
                    return False
            script = safe_build_file(gradlew, 65536)
            jar = safe_build_file(wrapper, 1048576)
            if script is None or jar is None:
                return False
            return (
                script.startswith(b"#!/")
                and bool(gradlew.stat().st_mode & 0o111)
                and hashlib.sha256(jar).hexdigest() == self._wrapper
            )
        except (OSError, TypeError, ValueError, KeyError):
            return False

    def _finish_failed(self, job_id: str, generation: int, code: str) -> dict[str, Any]:
        try:
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                generation,
                self._revision,
                authorized=True,
                failure_code=code,
            )
        except JobStoreError:
            return _result("uncertain", "uncertain", job_id, error="JOB_UNAVAILABLE")
        return _result("failed", "failed", job_id, error=code)

    def _artifact(self, job_id: str, action: str, result: RunResult) -> dict[str, str]:
        """Save private structured report; never persist any raw Gradle logs."""
        apk_handle = ""
        if action == "assemble_debug":
            path = self._root / "android/app/build/outputs/apk/debug/app-debug.apk"
            if any(part.is_symlink() for part in (path, *list(path.parents)[:5])):
                raise ValueError("Unsafe output location")
            content = safe_build_file(path, MAX_APK_BYTES)
            if content is None:
                raise ValueError("Missing APK output")
            try:
                inspect_zip(content, _APK_MIME)
            except ArchiveValidationError as exc:
                raise ValueError("Invalid APK output") from exc
            apk_handle = str(
                self._artifacts.put(self._artifact_owner, content, mime_type=_APK_MIME)["handle"]
            )
        record = {
            "schema_version": 1,
            "runtime": "host",
            "job_id": job_id,
            "action": action,
            "state": "succeeded",
            "exit_code": result.returncode,
            "output_stored": False,
            "apk_present": bool(apk_handle),
            "apk_handle": apk_handle or None,
        }
        serialized = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        report = self._artifacts.put(self._artifact_owner, serialized, mime_type="application/json")
        return {
            "report_handle": str(report["handle"]),
            "apk_handle": apk_handle,
            "result_sha256": hashlib.sha256(serialized).hexdigest(),
        }

    def submit(self, action: str, request_id: str, *, variant: str = "debug") -> dict[str, Any]:
        """One bounded allowlisted action, durable claim, fail-closed recovery."""
        if type(action) is not str or action not in TASKS or variant != "debug":
            return _result("blocked", None, error="INVALID_ACTION")
        if not isinstance(request_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}", request_id, re.ASCII
        ):
            return _result("blocked", None, error="INVALID_REQUEST")
        try:
            fd = self._project_lock()
        except OSError:
            return _result("blocked", None, error="JOB_UNAVAILABLE")
        if fd is None:
            try:
                prior = self._jobs.lookup_request(
                    self._owner, request_id, self._plan_digest(action, variant), self._revision
                )
            except JobStoreError as error:
                code = (
                    "IDEMPOTENCY_CONFLICT"
                    if error.code == "IDEMPOTENCY_CONFLICT"
                    else "JOB_UNAVAILABLE"
                )
                return _result("blocked", None, error=code)
            if prior is not None:
                return self._replay(
                    str(prior["state"]), str(prior["job_id"]), prior.get("result_digest")
                )
            return _result("in_progress", None, error="BUILD_BUSY")
        try:
            return self._submit_locked(action, request_id, variant)
        finally:
            os.close(fd)

    def _submit_locked(self, action: str, request_id: str, variant: str) -> dict[str, Any]:
        if not self._approved(action, variant):
            return _result("blocked", None, error="NOT_APPROVED")
        digest = self._plan_digest(action, variant)
        try:
            previous = self._jobs.lookup_request(self._owner, request_id, digest, self._revision)
            if previous is None or previous["state"] == "prepared":
                # A Host process may crash without terminating a Gradle child.
                # An expired or cancelled job is uncertain until an operator
                # reconciles it; never schedule a different request meanwhile.
                live = self._jobs.list_status(self._owner)
                if any(record["state"] in {"queued", "running", "uncertain"} for record in live):
                    return _result("blocked", None, error="RECOVERY_REQUIRED")
            job = self._jobs.prepare(
                self._owner,
                request_id,
                digest,
                identity=self._revision,
                authorized=True,
            )
            job_id = str(job["job_id"])
            if job["state"] != "prepared":
                return self._replay(str(job["state"]), job_id, job.get("result_digest"))
            self._jobs.queue(self._owner, job_id, identity=self._revision, authorized=True)
            claimed = self._jobs.claim(
                self._owner,
                job_id,
                _WORKER,
                self._revision,
                authorized=True,
            )
        except JobStoreError as error:
            if error.code in {"INVALID_TRANSITION", "NOT_CLAIMABLE"}:
                current = self._jobs.status(self._owner, job_id)
                if current["status"] == "ok":
                    state = str(current["job"]["state"])
                    return self._replay(state, job_id, current["job"].get("result_digest"))
            code = (
                "IDEMPOTENCY_CONFLICT"
                if error.code == "IDEMPOTENCY_CONFLICT"
                else "JOB_UNAVAILABLE"
            )
            return _result("blocked", None, error=code)

        argv = [
            str(self._root / "android" / "gradlew"),
            "--offline",
            "--no-daemon",
            *(["-PenableAndroidApp=true"] if action != "test_jvm" else []),
            *TASKS[action],
        ]
        try:
            try:
                before = self._output_stamp() if action == "assemble_debug" else None
            except ValueError:
                return self._finish_failed(job_id, claimed["generation"], "OUTPUT_INVALID")
            outcome = self._runner(argv, self._timeout, MAX_OUTPUT_BYTES, self._root / "android")
            if outcome.truncated:
                return self._finish_failed(job_id, claimed["generation"], "OUTPUT_LIMIT")
            if outcome.returncode != 0:
                return self._finish_failed(job_id, claimed["generation"], "BUILD_FAILED")
            try:
                if action == "assemble_debug" and self._output_stamp() == before:
                    raise ValueError("Build produced no fresh APK")
                stored = self._artifact(job_id, action, outcome)
            except ValueError:
                return self._finish_failed(job_id, claimed["generation"], "OUTPUT_INVALID")
            except (ArtifactStoreError, OSError):
                return self._finish_failed(job_id, claimed["generation"], "ARTIFACT_FAILED")
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                claimed["generation"],
                self._revision,
                authorized=True,
                result_digest=stored["result_sha256"],
            )
            return _result(
                "ok",
                "succeeded",
                job_id,
                report_handle=stored["report_handle"],
                apk_handle=stored["apk_handle"] or None,
                result_sha256=stored["result_sha256"],
            )
        except subprocess.TimeoutExpired:
            # The timed-out worker may have initiated effects. Never retry it.
            try:
                self._jobs.cancel(self._owner, job_id, identity=self._revision, authorized=True)
            except JobStoreError:
                pass
            return _result("uncertain", "uncertain", job_id, error="TIMEOUT")
        except (
            OSError,
            ValueError,
            RuntimeError,
            JobStoreError,
            ArtifactStoreError,
            TypeError,
            AttributeError,
        ):
            # Any unexpected partial effect is uncertain and must never replay.
            try:
                self._jobs.cancel(self._owner, job_id, identity=self._revision, authorized=True)
            except JobStoreError:
                pass
            return _result("uncertain", "uncertain", job_id, error="RUNNER_FAILED")

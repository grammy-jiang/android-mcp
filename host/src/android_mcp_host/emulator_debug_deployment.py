"""H3.f owner-pinned *synthetic-only* debug deployment receipts.

Real ADB install, launch, uninstall, physical target discovery and QEMU
mutation are absent. The public Host CLI never provides a fixture executor.
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

from android_mcp_host.avd_provision_support import OwnedAvdError, root_key
from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.command_runner import RunResult
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_debug_support import (
    APK_MIME,
    MAX_OUTPUT,
    _reply,
    cancel_fixture_job,
    check_install_receipt,
    debug_plan_digest,
    inspect_signed_fixture,
    parse_deploy_result,
    valid_digest,
    valid_package,
    verified_fake_target,
)
from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_REPORT = re.compile(r"art_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_ACTIONS = {"plan", "install", "launch", "uninstall", "cleanup", "cancel"}
_STATE = {
    "install": "synthetic_installed",
    "launch": "synthetic_launched",
    "uninstall": "synthetic_removed",
    "cleanup": "synthetic_removed",
}
MAX_TIMEOUT = 10.0
_WORKER = "h3f-synthetic-debug-deploy-worker"
Runner = Callable[[Sequence[str], float, int], RunResult]


def get_debug_deploy_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-emulator-debug-deploy.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host debug deployment schema")
    return value


class DebugDeployment:
    """Only an injected test fixture can simulate a private debug deployment."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        artifacts: PrivateArtifactStore,
        *,
        owner: str,
        artifact_owner: str,
        expected_package: str,
        fixture_runner: Runner | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or not artifacts.validate_owner(artifact_owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
            or not valid_package(expected_package)
            or not expected_package.startswith("org.example.synthetic.")
        ):
            raise ValueError("Invalid trusted fake-only debug deployment configuration")
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= MAX_TIMEOUT:
            raise ValueError("Invalid finite synthetic deployment deadline")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._artifacts = artifacts
        self._owner = owner
        self._artifact_owner = artifact_owner
        self._package = expected_package
        self._runner = fixture_runner
        self._timeout = float(timeout_s)
        self._installed: dict[tuple[str, str], tuple[str, str, str]] = {}

    @staticmethod
    def _digest(
        action: str,
        info: dict[str, Any],
        lifecycle_id: str,
        apk_handle: str,
        apk_sha: str,
        package: str,
        install_report: str | None,
    ) -> str:
        return debug_plan_digest(
            action,
            info,
            lifecycle_id,
            apk_handle,
            apk_sha,
            package,
            install_report,
        )

    def _apk(self, handle: str, expected: str, info: dict[str, Any]) -> bool:
        meta = self._artifacts.public_metadata(self._artifact_owner, handle)
        if meta["status"] != "ok" or meta["artifact"]["mime_type"] != APK_MIME:
            return False
        if meta["artifact"]["sha256"] != expected:
            return False
        if not 26 <= info["api"] <= 40:
            return False
        try:
            data = self._artifacts.read(self._artifact_owner, handle)
            secret = root_key(self._provisioner.private_root, create=False)
            return (
                secret is not None
                and hashlib.sha256(data).hexdigest() == expected
                and inspect_signed_fixture(data, secret, self._package, info["abi"]) is not None
            )
        except (ArtifactStoreError, OwnedAvdError, OSError):
            return False

    def _running(self, info: dict[str, Any], lifecycle_id: str) -> bool:
        return verified_fake_target(self._lifecycle, info, lifecycle_id)

    def _installed_receipt(
        self,
        info: dict[str, Any],
        lifecycle_id: str,
        apk_sha: str,
        install_report: str | None,
    ) -> bool:
        return check_install_receipt(
            self._artifacts,
            self._artifact_owner,
            self._installed.get((info["handle"], self._package)),
            install_report,
            info["handle"],
            self._package,
            lifecycle_id,
            apk_sha,
        )

    def _replay(self, job: dict[str, Any], info: dict[str, Any], apk_sha: str) -> dict[str, Any]:
        state = str(job["state"])
        result = _reply(
            "simulated"
            if state == "succeeded"
            else ("failed" if state == "failed" else "uncertain"),
            "unknown",
            name=info["name"],
            handle=info["handle"],
            package=self._package,
            apk_sha=apk_sha,
            job_id=str(job["job_id"]),
            report_sha=job.get("result_digest"),
        )
        digest = job.get("result_digest")
        if state != "succeeded" or not isinstance(digest, str):
            return result
        try:
            for record in self._artifacts.list_metadata(self._artifact_owner):
                if record["sha256"] != digest or record["mime_type"] != "application/json":
                    continue
                receipt = json.loads(self._artifacts.read(self._artifact_owner, record["handle"]))
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("job_id") != job["job_id"]
                    or receipt.get("avd_handle") != info["handle"]
                    or receipt.get("package_id") != self._package
                    or receipt.get("apk_sha256") != apk_sha
                    or receipt.get("synthetic_fixture_only") is not True
                ):
                    continue
                result["report_handle"] = record["handle"]
                break
        except (ArtifactStoreError, OSError, TypeError, KeyError, ValueError):
            pass
        return result

    def _commit(
        self,
        action: str,
        info: dict[str, Any],
        lifecycle_id: str,
        job_id: str,
        generation: int,
        apk_sha: str,
        result: RunResult,
    ) -> dict[str, Any]:
        if (
            type(result.returncode) is not int
            or type(result.truncated) is not bool
            or not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
            or result.truncated
            or result.stderr
        ):
            code = "OUTPUT_INVALID"
            good = None
        else:
            good = parse_deploy_result(result.stdout, action, info["name"], self._package)
            code = "OUTPUT_INVALID" if good is None else "FIXTURE_FAILED"
        if good is not True or result.returncode != 0:
            failure = code if good is not True else "FIXTURE_FAILED"
            self._jobs.complete(
                self._owner,
                job_id,
                _WORKER,
                generation,
                info["handle"],
                authorized=True,
                failure_code=failure,
            )
            return _reply("failed", "unknown", job_id=job_id, error=failure)
        state = _STATE[action]
        private = {
            "schema_version": 1,
            "runtime": "host",
            "job_id": job_id,
            "action": action,
            "state": state,
            "avd_handle": info["handle"],
            "lifecycle_job_id": lifecycle_id,
            "package_id": self._package,
            "apk_sha256": apk_sha,
            "synthetic_fixture_only": True,
        }
        encoded = json.dumps(private, sort_keys=True, separators=(",", ":")).encode("ascii")
        artifact = self._artifacts.put(
            self._artifact_owner,
            encoded,
            mime_type="application/json",
        )
        digest = hashlib.sha256(encoded).hexdigest()
        self._jobs.complete(
            self._owner,
            job_id,
            _WORKER,
            generation,
            info["handle"],
            authorized=True,
            result_digest=digest,
        )
        return _reply(
            "simulated",
            state,
            name=info["name"],
            handle=info["handle"],
            package=self._package,
            apk_sha=apk_sha,
            job_id=job_id,
            report_handle=artifact["handle"],
            report_sha=digest,
        )

    def _execute(
        self,
        action: str,
        info: dict[str, Any],
        lifecycle_id: str,
        apk_handle: str,
        apk_sha: str,
        request_id: str,
        install_report: str | None,
    ) -> dict[str, Any]:
        if not self._running(info, lifecycle_id):
            return _reply("blocked", "unknown", error="UNVERIFIED_TARGET")
        if action != "install" and not self._installed_receipt(
            info, lifecycle_id, apk_sha, install_report
        ):
            return _reply("blocked", "unknown", error="NOT_INSTALLED")
        digest = self._digest(
            action, info, lifecycle_id, apk_handle, apk_sha, self._package, install_report
        )
        try:
            previous = self._jobs.lookup_request(self._owner, request_id, digest, info["handle"])
            if previous is not None:
                return self._replay(previous, info, apk_sha)
            if any(
                row["state"] in {"prepared", "queued", "running", "uncertain"}
                and row["job_id"] != lifecycle_id
                for row in self._jobs.list_status(self._owner)
            ):
                return _reply("blocked", "unknown", error="RECOVERY_REQUIRED")
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
            return _reply("blocked", "unknown", error=code)
        argv = [
            "fixture-debug-deploy",
            "--action",
            action,
            "--avd",
            info["name"],
            "--lifecycle-job",
            lifecycle_id,
            "--package",
            self._package,
            "--apk-sha256",
            apk_sha,
        ]
        try:
            assert self._runner is not None
            result = self._runner(argv, self._timeout, MAX_OUTPUT)
            if not self._running(info, lifecycle_id):
                try:
                    self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass
                return _reply("uncertain", "unknown", job_id=job_id, error="UNVERIFIED_TARGET")
            if not self._apk(apk_handle, apk_sha, info):
                try:
                    self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
                except JobStoreError:
                    pass
                return _reply("uncertain", "unknown", job_id=job_id, error="BAD_APK")
            outcome = self._commit(
                action, info, lifecycle_id, job_id, claimed["generation"], apk_sha, result
            )
            if outcome["status"] == "simulated":
                key = (info["handle"], self._package)
                if action == "install":
                    self._installed[key] = (outcome["report_handle"], apk_sha, lifecycle_id)
                elif action in {"uninstall", "cleanup"}:
                    self._installed.pop(key, None)
            return outcome
        except subprocess.TimeoutExpired:
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
            return _reply("uncertain", "unknown", job_id=job_id, error="TIMEOUT")
        except (
            OSError,
            ValueError,
            RuntimeError,
            TypeError,
            AttributeError,
            JobStoreError,
            ArtifactStoreError,
        ):
            try:
                self._jobs.cancel(self._owner, job_id, identity=info["handle"], authorized=True)
            except JobStoreError:
                pass
            return _reply("uncertain", "unknown", job_id=job_id, error="RUNNER_FAILED")

    def _cancel(
        self,
        info: dict[str, Any],
        original_action: str,
        lifecycle_id: str,
        apk_handle: str,
        apk_sha: str,
        request_id: str,
        job_id: str,
        install_report: str | None,
    ) -> dict[str, Any]:
        digest = self._digest(
            original_action,
            info,
            lifecycle_id,
            apk_handle,
            apk_sha,
            self._package,
            install_report,
        )
        return cancel_fixture_job(
            self._jobs,
            self._owner,
            request_id,
            digest,
            info["handle"],
            job_id,
        )

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        package_id: str,
        *,
        request_id: str | None = None,
        install_report_handle: str | None = None,
        job_id: str | None = None,
        original_action: str | None = None,
    ) -> dict[str, Any]:
        """Return an inert plan or test-only synthetic receipt; never real ADB."""
        if action not in _ACTIONS:
            return _reply("blocked", "unknown", error="INVALID_ACTION")
        if (
            package_id != self._package
            or not valid_package(package_id)
            or not valid_digest(apk_sha256)
            or not isinstance(lifecycle_job_id, str)
            or _JOB.fullmatch(lifecycle_job_id) is None
        ):
            return _reply("blocked", "unknown", error="INVALID_INPUT")
        if action != "plan" and (
            not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None
        ):
            return _reply("blocked", "unknown", error="INVALID_INPUT")
        if action == "cancel" and (
            not isinstance(job_id, str)
            or _JOB.fullmatch(job_id) is None
            or original_action not in _STATE
        ):
            return _reply("blocked", "unknown", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", "unknown", error="NOT_OWNED")
        if not self._apk(apk_handle, apk_sha256, info):
            return _reply("blocked", "unknown", error="BAD_APK")
        if action == "plan":
            return _reply(
                "planned",
                "none",
                name=info["name"],
                handle=info["handle"],
                package=self._package,
                apk_sha=apk_sha256,
            )
        if self._runner is None:
            return _reply("blocked", "unknown", error="EXECUTION_DISABLED")
        if action == "cancel":
            assert request_id is not None and job_id is not None and original_action is not None
            return self._cancel(
                info,
                original_action,
                lifecycle_job_id,
                apk_handle,
                apk_sha256,
                request_id,
                job_id,
                install_report_handle,
            )
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", "unknown", error="JOB_UNAVAILABLE")
        if fd is None:
            return _reply("blocked", "unknown", error="RECOVERY_REQUIRED")
        try:
            assert request_id is not None
            return self._execute(
                action,
                info,
                lifecycle_job_id,
                apk_handle,
                apk_sha256,
                request_id,
                install_report_handle,
            )
        finally:
            os.close(fd)

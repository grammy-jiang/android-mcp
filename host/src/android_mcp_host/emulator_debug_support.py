"""Bounded, HMAC-attested *synthetic* APK fixtures; not Android signatures.

These receipts are private test harness proofs only. Real APK Signature
Scheme v1/v2/v3/v4 attestation is deliberately NOT inferred from them.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import zipfile
from typing import Any

from android_mcp_host.archive_validation import ArchiveValidationError, inspect_zip
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

APK_MIME = "application/vnd.android.package-archive"
SIGNATURE_MEMBER = "META-INF/MCP-SYNTHETIC-HMAC.txt"
MAX_OUTPUT = 8192
_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,6}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ACTIONS = {"install", "launch", "uninstall", "cleanup"}


def valid_package(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 128 and _PACKAGE.fullmatch(value) is not None


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def fixture_mac(members: dict[str, bytes], secret: bytes) -> str:
    """Test-only HMAC over an explicitly named set of bounded archive members."""
    content = [
        [name, hashlib.sha256(payload).hexdigest()] for name, payload in sorted(members.items())
    ]
    encoded = json.dumps(content, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


def inspect_signed_fixture(
    data: bytes, secret: bytes, expected_package: str, expected_abi: str
) -> dict[str, Any] | None:
    """Strict fake-only manifest, ABI and test-HMAC; never real APK signing proof."""
    try:
        meta, warnings = inspect_zip(data, APK_MIME)
        if warnings or meta.get("package_id") != expected_package:
            return None
        if meta.get("version_code", 0) < 1 or meta.get("abis") != [expected_abi]:
            return None
        if meta.get("resources_present") is not True:
            return None
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            names = set(zipped.namelist())
            expected = {
                "AndroidManifest.xml",
                "resources.arsc",
                f"lib/{expected_abi}/libfixture.so",
                SIGNATURE_MEMBER,
            }
            if names != expected:
                return None
            members = {name: zipped.read(name) for name in sorted(expected - {SIGNATURE_MEMBER})}
            signed = zipped.read(SIGNATURE_MEMBER)
        if len(signed) != 64 or _DIGEST.fullmatch(signed.decode("ascii")) is None:
            return None
        if not hmac.compare_digest(signed.decode("ascii"), fixture_mac(members, secret)):
            return None
        return {
            "package_id": expected_package,
            "abi": expected_abi,
            "version_code": meta["version_code"],
            "signature_provenance": "synthetic_hmac_fixture_only",
        }
    except (
        ArchiveValidationError,
        ValueError,
        OSError,
        UnicodeError,
        zipfile.BadZipFile,
        KeyError,
        RuntimeError,
    ):
        return None


def parse_deploy_result(output: object, action: str, name: str, package: str) -> bool | None:
    """Return true/false only for an exact bounded synthetic result envelope."""
    if not isinstance(output, str) or len(output.encode("utf-8")) > MAX_OUTPUT:
        return None
    try:
        value = json.loads(output)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(value, dict) or set(value) != {
        "synthetic",
        "action",
        "avd",
        "package",
        "success",
    }:
        return None
    if (
        value["synthetic"] is not True
        or action not in _ACTIONS
        or value["action"] != action
        or value["avd"] != name
        or value["package"] != package
        or type(value["success"]) is not bool
    ):
        return None
    return value["success"]


_ERRORS = {
    "INVALID_ACTION": "Unsupported debug deployment action",
    "INVALID_INPUT": "Debug deployment request has invalid fields",
    "NOT_OWNED": "Selected private AVD is not verified",
    "BAD_APK": "Private debug APK is invalid or not test-attested",
    "UNVERIFIED_TARGET": "Verified synthetic emulator session is unavailable",
    "EXECUTION_DISABLED": "Real Android debug deployment remains disabled",
    "NOT_INSTALLED": "No active owned synthetic install receipt exists",
    "RECOVERY_REQUIRED": "Earlier deployment job requires reconciliation",
    "JOB_UNAVAILABLE": "Durable debug deployment job is unavailable",
    "IDEMPOTENCY_CONFLICT": "Request does not match original deployment plan",
    "FIXTURE_FAILED": "Synthetic debug deployment operation failed",
    "OUTPUT_INVALID": "Synthetic deployment result was malformed or truncated",
    "TIMEOUT": "Synthetic deployment outcome is uncertain after timeout",
    "RUNNER_FAILED": "Synthetic runner or private storage failed",
}


def _reply(
    status: str,
    install_state: str,
    *,
    name: str | None = None,
    handle: str | None = None,
    package: str | None = None,
    apk_sha: str | None = None,
    job_id: str | None = None,
    report_handle: str | None = None,
    report_sha: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "install_state": install_state,
        "avd_name": name,
        "avd_handle": handle,
        "package_id": package,
        "apk_sha256": apk_sha,
        "job_id": job_id,
        "report_handle": report_handle,
        "report_sha256": report_sha,
        "signature_provenance": "synthetic_hmac_fixture_only",
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_deployment_enabled": False,
        "physical_device_writes_enabled": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


def cancel_fixture_job(
    store: DurableJobStore,
    owner: str,
    request_id: str,
    digest: str,
    avd_handle: str,
    job_id: str,
) -> dict[str, Any]:
    """Never cancel a lifecycle, instrumentation or unrelated deploy job."""
    try:
        record = store.lookup_request(owner, request_id, digest, avd_handle)
        if (
            record is None
            or record["job_id"] != job_id
            or record["state"] in {"succeeded", "failed", "cancelled"}
        ):
            return _reply("blocked", "unknown", error="JOB_UNAVAILABLE")
        store.cancel(owner, job_id, identity=avd_handle, authorized=True)
    except JobStoreError as error:
        if error.code == "IDEMPOTENCY_CONFLICT":
            return _reply("blocked", "unknown", error="IDEMPOTENCY_CONFLICT")
        return _reply("uncertain", "unknown", job_id=job_id, error="JOB_UNAVAILABLE")
    return _reply("uncertain", "unknown", job_id=job_id)


def debug_plan_digest(
    action: str,
    info: dict[str, Any],
    lifecycle_id: str,
    apk_handle: str,
    apk_sha: str,
    package: str,
    install_report: str | None,
) -> str:
    """Durable digest binds action, exact fixture, lifecycle and original receipt."""
    plan = {
        "protocol": "h3f-synthetic-debug-v1",
        "action": action,
        "target_handle": info["handle"],
        "image_sha": info["artifact_sha256"],
        "lifecycle_job": lifecycle_id,
        "apk_handle": apk_handle,
        "apk_sha": apk_sha,
        "package": package,
        "install_report": install_report if action != "install" else None,
    }
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def check_install_receipt(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    expected: tuple[str, str, str] | None,
    report_handle: str | None,
    avd_handle: str,
    package: str,
    lifecycle_id: str,
    apk_sha: str,
) -> bool:
    """Never adopt a foreign/revoked/private install receipt after Host restart."""
    if (
        not isinstance(report_handle, str)
        or re.fullmatch(r"art_[A-Za-z0-9_-]{32}", report_handle, re.ASCII) is None
    ):
        return False
    if expected != (report_handle, apk_sha, lifecycle_id):
        return False
    try:
        report = json.loads(artifacts.read(artifact_owner, report_handle))
        return (
            isinstance(report, dict)
            and report.get("action") == "install"
            and report.get("state") == "synthetic_installed"
            and report.get("avd_handle") == avd_handle
            and report.get("apk_sha256") == apk_sha
            and report.get("package_id") == package
            and report.get("lifecycle_job_id") == lifecycle_id
            and report.get("synthetic_fixture_only") is True
        )
    except (ArtifactStoreError, OSError, ValueError, TypeError):
        return False


def verified_fake_target(
    lifecycle: EmulatorLifecycle,
    info: dict[str, Any],
    lifecycle_id: str,
) -> bool:
    """Require positive in-process H3.c synthetic ownership, never ADB serials."""
    try:
        value = lifecycle.run(
            "status",
            info["name"],
            info["handle"],
            job_id=lifecycle_id,
        )
        return (
            value["status"] == "ok"
            and value["lifecycle_state"] == "running"
            and value["name"] == info["name"]
            and value["handle"] == info["handle"]
            and value["job_id"] == lifecycle_id
            and value["process_confirmed"] is True
            and value["synthetic_execution_enabled"] is True
            and value["real_emulator_execution_enabled"] is False
            and value["physical_device_writes_enabled"] is False
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, JobStoreError):
        return False

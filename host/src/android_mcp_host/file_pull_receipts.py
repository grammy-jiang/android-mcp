"""Privacy-preserving opaque receipts for H4.d synthetic app file pulls."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_ERRORS = {
    "INVALID_ACTION": "Unsupported bounded private file-export action",
    "INVALID_INPUT": "Invalid request, expected checksum or transfer limit",
    "SOURCE_DENIED": "Only explicitly allowlisted synthetic app exports are eligible",
    "NOT_OWNED": "Exact private disposable AVD ownership was not verified",
    "CONSENT_REQUIRED": "Independent narrow file-export grant is absent or expired",
    "EXECUTION_DISABLED": "Real ADB file pulling remains disabled",
    "UNVERIFIED_TARGET": "Exact synthetic AVD lifecycle was not verified",
    "RECOVERY_REQUIRED": "Previous transfer requires reconciliation",
    "JOB_UNAVAILABLE": "Private durable export job is unavailable",
    "IDEMPOTENCY_CONFLICT": "The export request no longer matches its first submission",
    "BAD_FRAME": "Untrusted synthetic file source or identity",
    "SYMLINK_DENIED": "Symlink or nonregular source is never exported",
    "PARTIAL_TRANSFER": "Synthetic transfer was not complete",
    "CHECKSUM_MISMATCH": "Export bytes do not match the pinned SHA-256",
    "TRANSFER_TOO_LARGE": "Synthetic exported file exceeded its size budget",
    "TIMEOUT": "Export timed out without a confirmed result",
    "RUNNER_FAILED": "Synthetic export or private storage failed",
    "ARTIFACT_EXPIRED": "Private file or verified receipt no longer exists",
    "NOT_ACTIVE": "No matching live private export job is cancellable",
    "CANCELLED": "Synthetic file export was cancelled; outcome remains uncertain",
}


def _reply(
    status: str,
    state: str = "none",
    *,
    name: str | None = None,
    handle: str | None = None,
    lifecycle_id: str | None = None,
    package_id: str | None = None,
    filename: str | None = None,
    mime: str | None = None,
    job_id: str | None = None,
    artifact_handle: str | None = None,
    receipt_handle: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    max_bytes: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "file_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "package_id": package_id,
        "filename": filename,
        "mime_type": mime,
        "job_id": job_id,
        "artifact_handle": artifact_handle,
        "receipt_handle": receipt_handle,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "max_bytes": max_bytes,
        "source_kind": "synthetic_app_export_only",
        "privacy_class": "sensitive_private",
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_pull_enabled": False,
        "physical_device_reads_enabled": False,
        "physical_device_writes_enabled": False,
        "raw_content_returned": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


def replay_export(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    job: dict[str, Any],
    *,
    name: str,
    avd_handle: str,
    lifecycle_id: str,
    package: str,
    remote_path: str,
    filename: str,
    expected_sha: str,
    mime: str,
    cap: int,
) -> dict[str, Any]:
    jid = str(job["job_id"])
    base: dict[str, Any] = {
        "name": name,
        "handle": avd_handle,
        "lifecycle_id": lifecycle_id,
        "package_id": package,
        "filename": filename,
        "mime": mime,
        "max_bytes": cap,
        "job_id": jid,
    }
    if job["state"] == "failed":
        return _reply("failed", "unknown", error="BAD_FRAME", **base)
    if job["state"] != "succeeded" or not isinstance(job.get("result_digest"), str):
        return _reply("uncertain", "unknown", error="RECOVERY_REQUIRED", **base)
    path_hash = hashlib.sha256(remote_path.encode("ascii")).hexdigest()
    try:
        for item in artifacts.list_metadata(artifact_owner):
            if item["mime_type"] != "application/json" or item["sha256"] != job["result_digest"]:
                continue
            receipt = json.loads(artifacts.read(artifact_owner, item["handle"]))
            if (
                not isinstance(receipt, dict)
                or receipt.get("purpose") != "h4d-synthetic-private-file-pull-v1"
                or receipt.get("job_id") != jid
                or receipt.get("avd_handle") != avd_handle
                or receipt.get("lifecycle_job_id") != lifecycle_id
                or receipt.get("package_id") != package
                or receipt.get("source_path_sha256") != path_hash
                or receipt.get("filename") != filename
                or receipt.get("mime_type") != mime
                or receipt.get("sha256") != expected_sha
                or receipt.get("synthetic_fixture_only") is not True
            ):
                continue
            payload = artifacts.read(artifact_owner, receipt["artifact_handle"])
            if not 1 <= len(payload) <= cap or hashlib.sha256(payload).hexdigest() != expected_sha:
                continue
            metadata = artifacts.public_metadata(artifact_owner, receipt["artifact_handle"])
            if metadata["status"] != "ok" or metadata["artifact"]["mime_type"] != mime:
                continue
            return _reply(
                "ok",
                "pulled_synthetic",
                artifact_handle=receipt["artifact_handle"],
                receipt_handle=item["handle"],
                sha256=expected_sha,
                size_bytes=len(payload),
                **base,
            )
    except (ArtifactStoreError, KeyError, OSError, TypeError, ValueError):
        pass
    return _reply("uncertain", "unknown", error="ARTIFACT_EXPIRED", **base)

"""Typed private synthetic file-import receipts and owner-scoped replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_ERRORS = {
    "INVALID_ACTION": "Unsupported private synthetic import action",
    "INVALID_INPUT": "Invalid imported file, request, checksum or transfer bounds",
    "DESTINATION_DENIED": "Only an exact synthetic app-owned import leaf is eligible",
    "NOT_OWNED": "Selected disposable synthetic AVD is not verified",
    "MUTATION_DISABLED": "Real Android/physical file writes remain disabled",
    "UNVERIFIED_TARGET": "Exact synthetic AVD lifecycle was not confirmed",
    "BAD_ARTIFACT": "Owner-scoped private source artifact did not verify",
    "CONSENT_REQUIRED": "Independent signed synthetic import grant is not valid",
    "RECOVERY_REQUIRED": "Previous synthetic mutation requires reconciliation",
    "IDEMPOTENCY_CONFLICT": "This private destination has a conflicting request",
    "JOB_UNAVAILABLE": "Private durable file import job is unavailable",
    "BAD_FRAME": "Synthetic file import returned spoofed metadata",
    "OVERWRITE_DENIED": "Synthetic source would overwrite or follow a link",
    "PARTIAL_WRITE": "Synthetic file write was incomplete or unconfirmed",
    "CHECKSUM_MISMATCH": "Synthetic destination checksum or size was incorrect",
    "TIMEOUT": "Synthetic import timed out, outcome uncertain",
    "RUNNER_FAILED": "Synthetic import or its private receipt is unavailable",
    "ARTIFACT_EXPIRED": "Private import receipt is revoked or expired",
    "NOT_ACTIVE": "No matching live synthetic file import can be cancelled",
    "CANCELLED": "Synthetic import was cancelled with uncertain outcome",
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
    job_id: str | None = None,
    report_handle: str | None = None,
    report_sha256: str | None = None,
    artifact_sha256: str | None = None,
    bytes_written: int | None = None,
    mime_type: str | None = None,
    max_bytes: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "push_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "package_id": package_id,
        "destination_filename": filename,
        "job_id": job_id,
        "report_handle": report_handle,
        "report_sha256": report_sha256,
        "artifact_sha256": artifact_sha256,
        "bytes_written": bytes_written,
        "mime_type": mime_type,
        "max_bytes": max_bytes,
        "synthetic_signature_provenance": "synthetic_hmac_fixture_only",
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_push_enabled": False,
        "physical_device_writes_enabled": False,
        "raw_content_returned": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


def replay_import(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    job: dict[str, Any],
    info: dict[str, Any],
    lifecycle_id: str,
    package_id: str,
    dest: str,
    filename: str,
    token: str,
    sha: str,
    mime: str,
    maximum: int,
) -> dict[str, Any]:
    jid = str(job["job_id"])
    base: dict[str, Any] = {
        "name": info["name"],
        "handle": info["handle"],
        "lifecycle_id": lifecycle_id,
        "package_id": package_id,
        "filename": filename,
        "job_id": jid,
        "artifact_sha256": sha,
        "mime_type": mime,
        "max_bytes": maximum,
    }
    if job["state"] == "failed":
        return _reply("failed", "unknown", error="BAD_FRAME", **base)
    if job["state"] != "succeeded" or not isinstance(job.get("result_digest"), str):
        return _reply("uncertain", "unknown", error="RECOVERY_REQUIRED", **base)
    digest = hashlib.sha256(dest.encode("ascii")).hexdigest()
    try:
        for record in artifacts.list_metadata(artifact_owner):
            if (
                record["mime_type"] != "application/json"
                or record["sha256"] != job["result_digest"]
            ):
                continue
            fields = json.loads(artifacts.read(artifact_owner, record["handle"]))
            if (
                not isinstance(fields, dict)
                or fields.get("purpose") != "h4e-synthetic-atomic-import-v1"
                or fields.get("job_id") != jid
                or fields.get("avd_handle") != info["handle"]
                or fields.get("lifecycle_job_id") != lifecycle_id
                or fields.get("package_id") != package_id
                or fields.get("destination_sha256") != digest
                or fields.get("artifact_handle") != token
                or fields.get("artifact_sha256") != sha
                or fields.get("mime_type") != mime
                or fields.get("synthetic_fixture_only") is not True
                or type(fields.get("bytes_written")) is not int
                or not 1 <= fields["bytes_written"] <= maximum
            ):
                continue
            source = artifacts.public_metadata(artifact_owner, token)
            if (
                source["status"] != "ok"
                or source["artifact"]["sha256"] != sha
                or source["artifact"]["mime_type"] != mime
                or source["artifact"]["size_bytes"] != fields["bytes_written"]
            ):
                continue
            if hashlib.sha256(artifacts.read(artifact_owner, token)).hexdigest() != sha:
                continue
            return _reply(
                "simulated",
                "imported_synthetic",
                report_handle=record["handle"],
                report_sha256=record["sha256"],
                bytes_written=fields["bytes_written"],
                **base,
            )
    except (ArtifactStoreError, KeyError, ValueError, TypeError, OSError):
        pass
    return _reply("uncertain", "unknown", error="ARTIFACT_EXPIRED", **base)

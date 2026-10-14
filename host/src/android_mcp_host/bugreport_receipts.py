"""Private metadata-only synthetic bugreport receipts and validated replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from android_mcp_host.bugreport_support import verified_redacted_zip
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_ERRORS = {
    "INVALID_ACTION": "Only private bugreport plan, collect or cancel are supported",
    "INVALID_INPUT": "Invalid bounded synthetic bugreport identifiers",
    "NOT_OWNED": "Exact disposable synthetic AVD ownership is unavailable",
    "CONSENT_REQUIRED": "Independent expiring private diagnostic approval is absent",
    "EXECUTION_DISABLED": "Real Android bugreport collection remains disabled",
    "UNVERIFIED_TARGET": "Exact synthetic emulator lifecycle is not available",
    "RECOVERY_REQUIRED": "Previous synthetic diagnostic requires reconciliation",
    "JOB_UNAVAILABLE": "Private durable diagnostic job is unavailable",
    "IDEMPOTENCY_CONFLICT": "This bugreport differs from the original request",
    "BAD_FRAME": "Synthetic bugreport result or marker was not trusted",
    "BAD_ARCHIVE": "Bugreport ZIP was unsafe, invalid or unsanitizable",
    "TIMEOUT": "Synthetic bugreport timed out, state is uncertain",
    "RUNNER_FAILED": "Synthetic diagnostic or private storage failed",
    "ARTIFACT_EXPIRED": "Private sanitized report or receipt is unavailable",
    "NOT_ACTIVE": "No exact active synthetic bugreport job can be cancelled",
    "CANCELLED": "Synthetic diagnostic cancelled with uncertain outcome",
}


def _reply(
    status: str,
    state: str = "none",
    *,
    name: str | None = None,
    handle: str | None = None,
    lifecycle_id: str | None = None,
    job_id: str | None = None,
    artifact_handle: str | None = None,
    receipt_handle: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    redacted_lines: int | None = None,
    retention_seconds: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "report_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "job_id": job_id,
        "artifact_handle": artifact_handle,
        "receipt_handle": receipt_handle,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "redacted_lines": redacted_lines,
        "retention_seconds": retention_seconds,
        "mime_type": "application/zip",
        "privacy_class": "sensitive_private",
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "sanitized_only": True,
        "real_bugreport_enabled": False,
        "physical_device_reads_enabled": False,
        "physical_device_writes_enabled": False,
        "raw_content_returned": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


def replay_bugreport(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    job: dict[str, Any],
    *,
    name: str,
    handle: str,
    lifecycle_id: str,
) -> dict[str, Any]:
    jid = str(job["job_id"])
    base: dict[str, Any] = {
        "name": name,
        "handle": handle,
        "lifecycle_id": lifecycle_id,
        "job_id": jid,
    }
    if job["state"] == "failed":
        return _reply("failed", "unknown", error="BAD_ARCHIVE", **base)
    if job["state"] != "succeeded" or not isinstance(job.get("result_digest"), str):
        return _reply("uncertain", "unknown", error="RECOVERY_REQUIRED", **base)
    try:
        for item in artifacts.list_metadata(artifact_owner):
            if item["mime_type"] != "application/json" or item["sha256"] != job["result_digest"]:
                continue
            receipt = json.loads(artifacts.read(artifact_owner, item["handle"]))
            if (
                not isinstance(receipt, dict)
                or receipt.get("purpose") != "h5a-private-sanitized-bugreport-v1"
                or receipt.get("job_id") != jid
                or receipt.get("avd_handle") != handle
                or receipt.get("lifecycle_job_id") != lifecycle_id
                or receipt.get("synthetic_fixture_only") is not True
                or receipt.get("sanitized_only") is not True
                or type(receipt.get("redacted_lines")) is not int
                or not 0 <= receipt["redacted_lines"] <= 128
                or type(receipt.get("retention_seconds")) is not int
                or not 1 <= receipt["retention_seconds"] <= 300
            ):
                continue
            raw = artifacts.read(artifact_owner, receipt["artifact_handle"])
            if (
                hashlib.sha256(raw).hexdigest() != receipt.get("sha256")
                or not verified_redacted_zip(raw)
                or len(raw) != receipt.get("size_bytes")
            ):
                continue
            meta = artifacts.public_metadata(artifact_owner, receipt["artifact_handle"])
            if (
                meta["status"] != "ok"
                or meta["artifact"]["mime_type"] != "application/zip"
                or meta["artifact"]["sha256"] != receipt["sha256"]
            ):
                continue
            return _reply(
                "ok",
                "sanitized_synthetic",
                artifact_handle=receipt["artifact_handle"],
                receipt_handle=item["handle"],
                sha256=receipt["sha256"],
                size_bytes=len(raw),
                redacted_lines=receipt["redacted_lines"],
                retention_seconds=receipt["retention_seconds"],
                **base,
            )
    except (ArtifactStoreError, OSError, TypeError, ValueError, KeyError):
        pass
    return _reply("uncertain", "unknown", error="ARTIFACT_EXPIRED", **base)

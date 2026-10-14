"""Private metadata-only synthetic screen recording receipts and replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.screenrecord_support import InvalidSyntheticVideo, validate_video

_MIME = "video/mp4"
_ERRORS = {
    "INVALID_ACTION": "Unsupported private screen recording operation",
    "INVALID_INPUT": "Invalid bounded screen recording input",
    "NOT_OWNED": "Exact private disposable AVD ownership is unavailable",
    "CONSENT_REQUIRED": "Trusted expiring recording consent is unavailable",
    "EXECUTION_DISABLED": "Real ADB screen recording execution is disabled",
    "UNVERIFIED_TARGET": "Exact synthetic AVD lifecycle is not verified",
    "RECOVERY_REQUIRED": "Prior fixture operation requires trusted reconciliation",
    "IDEMPOTENCY_CONFLICT": "Recording request has changed since first submission",
    "JOB_UNAVAILABLE": "Private durable recording job is unavailable",
    "BAD_FRAME": "Synthetic video receipt identity is invalid",
    "BAD_VIDEO": "Synthetic media does not match bounded MP4 format",
    "SECURE_CONTENT": "Protected or locked window recording is forbidden",
    "TIMEOUT": "Synthetic recording timed out, outcome uncertain",
    "RUNNER_FAILED": "Bounded synthetic recorder is unavailable",
    "ARTIFACT_EXPIRED": "Private video or its receipt is no longer available",
    "CANCELLED": "Recording was cancelled; completion remains uncertain",
    "NOT_ACTIVE": "Recording has no active cancellable job",
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
    duration_s: int | None = None,
    display_id: int | None = None,
    codec: str | None = None,
    max_bytes: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "record_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "job_id": job_id,
        "artifact_handle": artifact_handle,
        "receipt_handle": receipt_handle,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "duration_s": duration_s,
        "display_id": display_id,
        "codec": codec,
        "max_bytes": max_bytes,
        "mime_type": _MIME,
        "privacy_class": "sensitive_private",
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_recording_enabled": False,
        "physical_device_writes_enabled": False,
        "raw_media_returned": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


def replay_record(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    prior: dict[str, Any],
    info: dict[str, Any],
    lid: str,
    duration: int,
    display: int,
    codec: str,
    cap: int,
) -> dict[str, Any]:
    jid = str(prior["job_id"])
    base = {
        "name": info["name"],
        "handle": info["handle"],
        "lifecycle_id": lid,
        "job_id": jid,
        "duration_s": duration,
        "display_id": display,
        "codec": codec,
        "max_bytes": cap,
    }
    state = prior["state"]
    if state == "failed":
        return _reply("failed", "unknown", error="BAD_VIDEO", **base)
    if state != "succeeded" or not isinstance(prior.get("result_digest"), str):
        return _reply("uncertain", "unknown", error="RECOVERY_REQUIRED", **base)
    try:
        for meta in artifacts.list_metadata(artifact_owner):
            if meta["mime_type"] != "application/json" or meta["sha256"] != prior["result_digest"]:
                continue
            receipt = json.loads(artifacts.read(artifact_owner, meta["handle"]))
            if (
                not isinstance(receipt, dict)
                or receipt.get("purpose") != "h4c-synthetic-screenrecord-v1"
                or receipt.get("job_id") != jid
                or receipt.get("avd_handle") != info["handle"]
                or receipt.get("lifecycle_job_id") != lid
                or receipt.get("duration_s") != duration
                or receipt.get("display_id") != display
                or receipt.get("codec") != codec
            ):
                continue
            clip = artifacts.read(artifact_owner, receipt["artifact_handle"])
            validate_video(clip, maximum=cap)
            if hashlib.sha256(clip).hexdigest() != receipt["sha256"]:
                continue
            return _reply(
                "ok",
                "captured_synthetic",
                receipt_handle=meta["handle"],
                artifact_handle=receipt["artifact_handle"],
                sha256=receipt["sha256"],
                size_bytes=len(clip),
                **base,
            )
    except (
        ArtifactStoreError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        InvalidSyntheticVideo,
    ):
        pass
    return _reply("uncertain", "unknown", error="ARTIFACT_EXPIRED", **base)

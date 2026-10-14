"""H5.c private synthetic Perfetto receipt verification and safe idempotent replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from android_mcp_host.perfetto_trace_support import (
    TRACE_VERSION,
    reply,
    valid_sanitized_trace,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError


def replay_trace(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    job: dict[str, Any],
    *,
    name: str,
    handle: str,
    lifecycle: str,
    profile: str,
    duration_s: int,
    max_bytes: int,
) -> dict[str, Any]:
    jid = str(job["job_id"])
    base: dict[str, Any] = {
        "name": name,
        "handle": handle,
        "lifecycle": lifecycle,
        "profile": profile,
        "duration_s": duration_s,
        "max_bytes": max_bytes,
        "job_id": jid,
    }
    if job["state"] == "failed":
        return reply("failed", state="unknown", error="BAD_TRACE", **base)
    if job["state"] != "succeeded" or not isinstance(job.get("result_digest"), str):
        return reply("uncertain", state="unknown", error="RECOVERY_REQUIRED", **base)
    try:
        for item in artifacts.list_metadata(artifact_owner):
            if item["mime_type"] != "application/json" or item["sha256"] != job["result_digest"]:
                continue
            receipt = json.loads(artifacts.read(artifact_owner, item["handle"]))
            if (
                type(receipt) is not dict
                or receipt.get("purpose") != "h5c-sanitized-synthetic-perfetto-v1"
                or receipt.get("trace_format") != TRACE_VERSION
                or receipt.get("schema_version") != 1
                or receipt.get("fixture_version") != "mcp-fixture-1"
                or receipt.get("job_id") != jid
                or receipt.get("avd_handle") != handle
                or receipt.get("lifecycle_job_id") != lifecycle
                or receipt.get("profile") != profile
                or receipt.get("duration_s") != duration_s
                or receipt.get("max_bytes") != max_bytes
                or receipt.get("synthetic_fixture_only") is not True
                or receipt.get("sanitized_only") is not True
                or type(receipt.get("sample_count")) is not int
                or not 1 <= receipt["sample_count"] <= 128
                or type(receipt.get("redacted_lines")) is not int
                or not 0 <= receipt["redacted_lines"] <= 256
                or type(receipt.get("retention_seconds")) is not int
                or not 1 <= receipt["retention_seconds"] <= 300
            ):
                continue
            saved = artifacts.read(artifact_owner, receipt["artifact_handle"])
            if (
                hashlib.sha256(saved).hexdigest() != receipt.get("sha256")
                or len(saved) != receipt.get("size_bytes")
                or not valid_sanitized_trace(saved, profile=profile, duration_s=duration_s)
            ):
                continue
            trace = json.loads(saved)
            if len(trace["samples"]) != receipt["sample_count"]:
                continue
            meta = artifacts.public_metadata(artifact_owner, receipt["artifact_handle"])
            if (
                meta["status"] != "ok"
                or meta["artifact"]["mime_type"] != "application/json"
                or meta["artifact"]["sha256"] != receipt["sha256"]
            ):
                continue
            return reply(
                "ok",
                state="synthetic_sanitized",
                artifact_handle=receipt["artifact_handle"],
                receipt_handle=item["handle"],
                sha256=receipt["sha256"],
                size_bytes=len(saved),
                sample_count=receipt["sample_count"],
                redacted_lines=receipt["redacted_lines"],
                ttl_s=receipt["retention_seconds"],
                **base,
            )
    except (ArtifactStoreError, OSError, ValueError, TypeError, KeyError, OverflowError):
        pass
    return reply("uncertain", state="unknown", error="ARTIFACT_EXPIRED", **base)

"""Durable exact-plan cancellation of a synthetic test-only file import."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.file_push_receipts import _reply
from android_mcp_host.file_push_support import plan_digest, request_slot


def cancel_import(
    jobs: DurableJobStore,
    owner: str,
    info: dict[str, Any],
    lid: str,
    token: str,
    sha: str,
    dest: str,
    filename: str,
    mime: str,
    maximum: int,
    request: str,
    jid: str,
    package: str,
    signal: Callable[[str], None],
) -> dict[str, Any]:
    """Never cancel an unrelated job; no real device transport is touched."""
    base: dict[str, Any] = {
        "name": info["name"],
        "handle": info["handle"],
        "lifecycle_id": lid,
        "package_id": package,
        "filename": filename,
        "artifact_sha256": sha,
        "mime_type": mime,
        "max_bytes": maximum,
        "job_id": jid,
    }
    try:
        prior = jobs.lookup_request(
            owner,
            request_slot(lid, dest),
            plan_digest(info, lid, dest, token, sha, mime, request, maximum),
            info["handle"],
        )
        if prior is None or prior["job_id"] != jid:
            return _reply("blocked", error="NOT_ACTIVE", **base)
        if prior["state"] == "uncertain":
            return _reply("uncertain", "unknown", error="CANCELLED", **base)
        if prior["state"] not in {"prepared", "queued", "running"}:
            return _reply("blocked", error="NOT_ACTIVE", **base)
        jobs.cancel(owner, jid, identity=info["handle"], authorized=True)
        signal(jid)
        return _reply("uncertain", "unknown", error="CANCELLED", **base)
    except JobStoreError as error:
        reason = (
            "IDEMPOTENCY_CONFLICT" if error.code == "IDEMPOTENCY_CONFLICT" else "JOB_UNAVAILABLE"
        )
        return _reply("blocked", error=reason, **base)

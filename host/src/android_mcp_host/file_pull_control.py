"""H4.d exact-owner durable cancellation, never an ADB process or path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.file_pull_receipts import _reply
from android_mcp_host.file_pull_support import transfer_digest, transfer_slot


def cancel_export(
    jobs: DurableJobStore,
    owner: str,
    info: dict[str, Any],
    lid: str,
    remote: str,
    filename: str,
    request: str,
    expected_sha: str,
    mime: str,
    cap: int,
    jid: str,
    stop: Callable[[str], None],
) -> dict[str, Any]:
    """Verify exact durable plan/job before signalling a synthetic fixture."""
    base: dict[str, Any] = {
        "name": info["name"],
        "handle": info["handle"],
        "lifecycle_id": lid,
        "package_id": None,  # no private source data in cancellation response
        "filename": filename,
        "mime": mime,
        "max_bytes": cap,
        "job_id": jid,
    }
    try:
        row = jobs.lookup_request(
            owner,
            transfer_slot(lid, remote),
            transfer_digest(info, lid, remote, request, expected_sha, mime, cap),
            info["handle"],
        )
        if row is None or row["job_id"] != jid:
            return _reply("blocked", error="NOT_ACTIVE", **base)
        if row["state"] == "uncertain":
            return _reply("uncertain", "unknown", error="CANCELLED", **base)
        if row["state"] not in {"prepared", "queued", "running"}:
            return _reply("blocked", error="NOT_ACTIVE", **base)
        jobs.cancel(owner, jid, identity=info["handle"], authorized=True)
        stop(jid)
        return _reply("uncertain", "unknown", error="CANCELLED", **base)
    except JobStoreError as error:
        code = "IDEMPOTENCY_CONFLICT" if error.code == "IDEMPOTENCY_CONFLICT" else "JOB_UNAVAILABLE"
        return _reply("blocked", error=code, **base)

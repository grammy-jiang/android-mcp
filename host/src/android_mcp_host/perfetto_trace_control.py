"""Exact trace cancellation: never cancel an unrelated private job."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.perfetto_trace_support import plan_digest, reply


def cancel_trace(
    jobs: DurableJobStore,
    owner: str,
    info: dict[str, Any],
    lid: str,
    request: str,
    profile: str,
    duration_s: int,
    max_bytes: int,
    ttl_s: int,
    job_id: str,
    signal: Callable[[str], None],
) -> dict[str, Any]:
    base = {
        "name": info["name"],
        "handle": info["handle"],
        "lifecycle": lid,
        "profile": profile,
        "duration_s": duration_s,
        "max_bytes": max_bytes,
        "job_id": job_id,
    }
    try:
        prior = jobs.lookup_request(
            owner,
            "h5c-perfetto-" + lid,
            plan_digest(info["handle"], lid, request, profile, duration_s, max_bytes, ttl_s),
            info["handle"],
        )
        if prior is None or prior["job_id"] != job_id:
            return reply("blocked", error="NOT_ACTIVE", **base)
        if prior["state"] == "uncertain":
            return reply("uncertain", state="unknown", error="CANCELLED", **base)
        if prior["state"] not in {"prepared", "queued", "running"}:
            return reply("blocked", error="NOT_ACTIVE", **base)
        jobs.cancel(owner, job_id, identity=info["handle"], authorized=True)
        signal(job_id)
        return reply("uncertain", state="unknown", error="CANCELLED", **base)
    except JobStoreError as error:
        code = "IDEMPOTENCY_CONFLICT" if error.code == "IDEMPOTENCY_CONFLICT" else "JOB_UNAVAILABLE"
        return reply("blocked", error=code, **base)

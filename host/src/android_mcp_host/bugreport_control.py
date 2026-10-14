"""H5.a exact-owner cancellation of one synthetic private bugreport."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from android_mcp_host.bugreport_receipts import _reply
from android_mcp_host.bugreport_support import BUGREPORTZ_MARKER
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.ui_action_support import valid_request_id


def bugreport_slot(lifecycle_id: str) -> str:
    return "h5a-bugreport-" + lifecycle_id


def bugreport_digest(avd_handle: str, lifecycle_id: str, request_id: str) -> str:
    fields = {
        "purpose": "h5a-sanitized-synthetic-v1",
        "handle": avd_handle,
        "lifecycle": lifecycle_id,
        "request": request_id,
        "marker": BUGREPORTZ_MARKER,
    }
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def cancel_bugreport(
    jobs: DurableJobStore,
    owner: str,
    info: dict[str, Any],
    lid: str,
    request_id: str,
    job_id: str,
    signal: Callable[[str], None],
) -> dict[str, Any]:
    base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lid, "job_id": job_id}
    if not valid_request_id(request_id):
        return _reply("blocked", error="INVALID_INPUT", **base)
    try:
        prior = jobs.lookup_request(
            owner,
            bugreport_slot(lid),
            bugreport_digest(info["handle"], lid, request_id),
            info["handle"],
        )
        if prior is None or prior["job_id"] != job_id:
            return _reply("blocked", error="NOT_ACTIVE", **base)
        if prior["state"] == "uncertain":
            return _reply("uncertain", "unknown", error="CANCELLED", **base)
        if prior["state"] not in {"prepared", "queued", "running"}:
            return _reply("blocked", error="NOT_ACTIVE", **base)
        jobs.cancel(owner, job_id, identity=info["handle"], authorized=True)
        signal(job_id)
        return _reply("uncertain", "unknown", error="CANCELLED", **base)
    except JobStoreError as error:
        code = "IDEMPOTENCY_CONFLICT" if error.code == "IDEMPOTENCY_CONFLICT" else "JOB_UNAVAILABLE"
        return _reply("blocked", error=code, **base)

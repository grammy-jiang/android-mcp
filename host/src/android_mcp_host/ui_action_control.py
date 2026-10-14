"""Exact-plan durable cancellation of a single synthetic UI input action."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.ui_action_receipts import _reply
from android_mcp_host.ui_action_support import action_plan_digest, action_slot


def cancel_ui_action(
    jobs: DurableJobStore,
    owner: str,
    info: dict[str, Any],
    lifecycle_id: str,
    window_id: str,
    generation: int,
    rotation: int,
    focus: str,
    kind: str,
    intent_sha: str,
    request_id: str,
    job_id: str,
    signal: Callable[[str], None],
) -> dict[str, Any]:
    """No unrelated, finished, physical or user-selected job may be cancelled."""
    base: dict[str, Any] = {
        "name": info["name"],
        "handle": info["handle"],
        "lifecycle_id": lifecycle_id,
        "window_id": window_id,
        "generation": generation,
        "rotation": rotation,
        "focused_node_id": focus,
        "kind": kind,
        "intent_sha256": intent_sha,
        "job_id": job_id,
    }
    try:
        prior = jobs.lookup_request(
            owner,
            action_slot(lifecycle_id, window_id, intent_sha),
            action_plan_digest(
                info["handle"],
                lifecycle_id,
                window_id,
                generation,
                rotation,
                focus,
                intent_sha,
                request_id,
            ),
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
        reason = (
            "IDEMPOTENCY_CONFLICT" if error.code == "IDEMPOTENCY_CONFLICT" else "JOB_UNAVAILABLE"
        )
        return _reply("blocked", error=reason, **base)

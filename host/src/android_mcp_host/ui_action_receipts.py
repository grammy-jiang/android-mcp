"""H4.f private metadata-only synthetic UI action receipts, safe replay."""

from __future__ import annotations

import json
from typing import Any

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.private_artifact_support import ArtifactStoreError

_ERRORS = {
    "INVALID_ACTION": "Only fixed plan, execute or cancel UI actions are supported",
    "INVALID_INPUT": "Invalid bounded synthetic UI action fields",
    "NOT_OWNED": "Exact disposable AVD ownership was not verified",
    "MUTATION_DISABLED": "Real UI input/physical actions remain disabled",
    "CONSENT_REQUIRED": "Trusted expiring per-intent UI action grant is absent",
    "UNVERIFIED_TARGET": "Synthetic emulator lifecycle was not verified",
    "STALE_WINDOW": "Window generation, rotation or focused node changed",
    "WINDOW_PROTECTED": "Protected or locked UI windows cannot receive input",
    "CAPABILITY_UNAVAILABLE": "Exact synthetic UI witness is unavailable",
    "RECOVERY_REQUIRED": "Prior action requires trusted reconciliation",
    "JOB_UNAVAILABLE": "Private durable UI action job is unavailable",
    "IDEMPOTENCY_CONFLICT": "UI intent or request conflicts with previous execution",
    "BAD_FRAME": "Synthetic UI action response did not match exact target",
    "PARTIAL_ACTION": "UI fixture action may be incomplete or uncertain",
    "TIMEOUT": "Synthetic UI action timed out, outcome uncertain",
    "RUNNER_FAILED": "Synthetic UI fixture or private receipt failed",
    "ARTIFACT_EXPIRED": "Prior private UI receipt cannot be verified",
    "NOT_ACTIVE": "No matching active action can be cancelled",
    "CANCELLED": "UI action cancelled with uncertain outcome",
}


def _reply(
    status: str,
    state: str = "none",
    *,
    name: str | None = None,
    handle: str | None = None,
    lifecycle_id: str | None = None,
    window_id: str | None = None,
    generation: int | None = None,
    rotation: int | None = None,
    focused_node_id: str | None = None,
    kind: str | None = None,
    intent_sha256: str | None = None,
    job_id: str | None = None,
    report_handle: str | None = None,
    report_sha256: str | None = None,
    preview_argv: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "action_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "window_id": window_id,
        "window_generation": generation,
        "rotation": rotation,
        "focused_node_id": focused_node_id,
        "kind": kind,
        "intent_sha256": intent_sha256,
        "job_id": job_id,
        "action_id": job_id,
        "report_handle": report_handle,
        "report_sha256": report_sha256,
        "preview_argv": [] if preview_argv is None else preview_argv,
        "target": "disposable_emulator_only",
        "synthetic_fixture_only": True,
        "real_ui_input_enabled": False,
        "physical_device_writes_enabled": False,
        "generic_shell_enabled": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


def replay_ui_action(
    artifacts: PrivateArtifactStore,
    artifact_owner: str,
    job: dict[str, Any],
    *,
    name: str,
    handle: str,
    lifecycle_id: str,
    window_id: str,
    generation: int,
    rotation: int,
    focus: str,
    kind: str,
    intent_sha: str,
) -> dict[str, Any]:
    jid = str(job["job_id"])
    base: dict[str, Any] = {
        "name": name,
        "handle": handle,
        "lifecycle_id": lifecycle_id,
        "window_id": window_id,
        "generation": generation,
        "rotation": rotation,
        "focused_node_id": focus,
        "kind": kind,
        "intent_sha256": intent_sha,
        "job_id": jid,
    }
    if job["state"] == "failed":
        return _reply("failed", "unknown", error="BAD_FRAME", **base)
    if job["state"] != "succeeded" or not isinstance(job.get("result_digest"), str):
        return _reply("uncertain", "unknown", error="RECOVERY_REQUIRED", **base)
    try:
        for record in artifacts.list_metadata(artifact_owner):
            if (
                record["mime_type"] != "application/json"
                or record["sha256"] != job["result_digest"]
            ):
                continue
            receipt = json.loads(artifacts.read(artifact_owner, record["handle"]))
            if (
                not isinstance(receipt, dict)
                or receipt.get("purpose") != "h4f-private-synthetic-ui-action-v1"
                or receipt.get("job_id") != jid
                or receipt.get("avd_handle") != handle
                or receipt.get("lifecycle_job_id") != lifecycle_id
                or receipt.get("window_id") != window_id
                or receipt.get("window_generation") != generation
                or receipt.get("rotation") != rotation
                or receipt.get("focused_node_id") != focus
                or receipt.get("kind") != kind
                or receipt.get("intent_sha256") != intent_sha
                or receipt.get("synthetic_fixture_only") is not True
            ):
                continue
            return _reply(
                "simulated",
                "applied_synthetic",
                report_handle=record["handle"],
                report_sha256=record["sha256"],
                **base,
            )
    except (ArtifactStoreError, OSError, TypeError, ValueError, KeyError):
        pass
    return _reply("uncertain", "unknown", error="ARTIFACT_EXPIRED", **base)

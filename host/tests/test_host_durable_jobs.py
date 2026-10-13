"""H2.d six mandatory durable Host job and safe-uncertainty behavior cases.

Synthetic jobs never run any command or interact with a device.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.server import create_server

OWNER = "fixture-owner"
OTHER = "other-owner"
IDENTITY = "fixture-device-01"
WORKER = "fixture-worker-a"
PLAN = hashlib.sha256(b"synthetic bounded plan").hexdigest()
RESULT = hashlib.sha256(b"synthetic completed result").hexdigest()


def _store(root: Path, **kwargs: Any) -> Any:
    from android_mcp_host.durable_jobs import DurableJobStore

    return DurableJobStore(root / "private-jobs", **kwargs)


def _denied(action: Any, code: str) -> None:
    from android_mcp_host.durable_jobs import JobStoreError

    with pytest.raises(JobStoreError) as caught:
        action()
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


def test_t_h2d_01_persist_prepare_queue_claim_succeed_fail_receipts_and_audit(
    tmp_path: Path,
) -> None:
    clock = [1000.0]
    store = _store(tmp_path, clock=lambda: clock[0])
    prepared = store.prepare(OWNER, "request-001", PLAN, identity=IDENTITY, authorized=True)
    assert prepared["state"] == "prepared"
    assert prepared["job_id"].startswith("job_")
    assert prepared["plan_digest"] == PLAN
    assert prepared["result_digest"] is None
    assert "owner" not in prepared
    assert "path" not in prepared
    assert str(tmp_path) not in str(prepared)
    job_id = prepared["job_id"]

    assert store.queue(OWNER, job_id, identity=IDENTITY, authorized=True)["state"] == "queued"
    claimed = store.claim(OWNER, job_id, worker_id=WORKER, identity=IDENTITY, authorized=True)
    assert claimed["state"] == "running"
    assert claimed["attempts"] == 1 and claimed["generation"] == 1
    clock[0] += 2
    finished = store.complete(
        OWNER,
        job_id,
        worker_id=WORKER,
        generation=1,
        identity=IDENTITY,
        authorized=True,
        result_digest=RESULT,
    )
    assert finished["state"] == "succeeded"
    assert finished["result_digest"] == RESULT
    assert finished["finished_at"] == clock[0]
    assert finished["created_at"] == 1000.0

    reopened = _store(tmp_path, clock=lambda: clock[0])
    assert reopened.status(OWNER, job_id)["job"] == finished
    events = reopened.audit(OWNER, job_id)
    assert [entry["event"] for entry in events] == ["prepared", "queued", "claimed", "succeeded"]
    assert [entry["sequence"] for entry in events] == sorted(entry["sequence"] for entry in events)
    assert all("owner" not in event for event in events)

    second = reopened.prepare(OWNER, "request-002", PLAN, identity=IDENTITY, authorized=True)
    reopened.queue(OWNER, second["job_id"], identity=IDENTITY, authorized=True)
    reopened.claim(
        OWNER,
        second["job_id"],
        worker_id=WORKER,
        identity=IDENTITY,
        authorized=True,
    )
    failed = reopened.complete(
        OWNER,
        second["job_id"],
        worker_id=WORKER,
        generation=1,
        identity=IDENTITY,
        authorized=True,
        failure_code="SYNTHETIC_FAILURE",
    )
    assert failed["state"] == "failed" and failed["result_digest"] is None
    assert reopened.audit(OWNER, second["job_id"])[-1]["event"] == "failed"


def test_t_h2d_02_exact_request_digest_is_idempotent_conflicting_digest_denied(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = store.prepare(OWNER, "request-identity", PLAN, identity=IDENTITY, authorized=True)
    replay = store.prepare(OWNER, "request-identity", PLAN, identity=IDENTITY, authorized=True)
    assert first == replay
    assert len(store.list_status(OWNER)) == 1
    assert [event["event"] for event in store.audit(OWNER, first["job_id"])] == ["prepared"]

    _denied(
        lambda: store.prepare(
            OWNER, "request-identity", "a" * 64, identity=IDENTITY, authorized=True
        ),
        "IDEMPOTENCY_CONFLICT",
    )
    _denied(
        lambda: store.prepare(
            OWNER, "request-identity", PLAN, identity="another-target", authorized=True
        ),
        "IDEMPOTENCY_CONFLICT",
    )
    separate = store.prepare(OTHER, "request-identity", PLAN, identity=IDENTITY, authorized=True)
    assert separate["job_id"] != first["job_id"]
    assert store.status(OTHER, first["job_id"])["status"] == "not_found"


def test_t_h2d_03_invalid_transition_wrong_owner_stale_identity_and_denial(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _denied(
        lambda: store.prepare(OWNER, "request-001", PLAN, identity=IDENTITY),
        "NOT_AUTHORIZED",
    )
    prepared = store.prepare(OWNER, "request-001", PLAN, identity=IDENTITY, authorized=True)
    job_id = prepared["job_id"]
    for action, reason in (
        (
            lambda: store.claim(OWNER, job_id, WORKER, IDENTITY, authorized=True),
            "INVALID_TRANSITION",
        ),
        (
            lambda: store.complete(
                OWNER, job_id, WORKER, 1, IDENTITY, authorized=True, result_digest=RESULT
            ),
            "INVALID_TRANSITION",
        ),
        (lambda: store.queue(OTHER, job_id, identity=IDENTITY, authorized=True), "NOT_FOUND"),
        (
            lambda: store.queue(OWNER, job_id, identity="stale-device", authorized=True),
            "STALE_IDENTITY",
        ),
        (lambda: store.queue(OWNER, job_id, identity=IDENTITY, authorized=False), "NOT_AUTHORIZED"),
    ):
        _denied(action, reason)
    assert store.status(OWNER, job_id)["job"]["state"] == "prepared"
    assert len(store.audit(OWNER, job_id)) == 1

    assert store.queue(OWNER, job_id, identity=IDENTITY, authorized=True)["state"] == "queued"
    _denied(
        lambda: store.queue(OWNER, job_id, identity=IDENTITY, authorized=True),
        "INVALID_TRANSITION",
    )
    assert store.status(OWNER, job_id)["job"]["state"] == "queued"


def test_t_h2d_04_concurrent_workers_single_owner_generation_and_total_audit_order(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(OWNER, "race-request", PLAN, identity=IDENTITY, authorized=True)
    job_id = prepared["job_id"]
    store.queue(OWNER, job_id, identity=IDENTITY, authorized=True)

    def competing(worker: int) -> tuple[int, dict[str, Any] | str]:
        try:
            result = store.claim(
                OWNER,
                job_id,
                worker_id=f"worker-{worker:02d}",
                identity=IDENTITY,
                authorized=True,
            )
        except Exception as error:
            return worker, getattr(error, "code", type(error).__name__)
        return worker, result

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(competing, range(16)))
    winners = [(i, result) for i, result in results if isinstance(result, dict)]
    assert len(winners) == 1
    assert all(result == "NOT_CLAIMABLE" for _, result in results if not isinstance(result, dict))
    assert winners[0][1]["attempts"] == 1
    assert winners[0][1]["generation"] == 1
    events = store.audit(OWNER, job_id)
    assert [item["event"] for item in events] == ["prepared", "queued", "claimed"]
    assert len({entry["sequence"] for entry in events}) == 3
    assert store.status(OWNER, job_id)["job"]["state"] == "running"


def test_t_h2d_05_cancel_timeout_restart_uncertainty_blocks_reexecution(
    tmp_path: Path,
) -> None:
    clock = [3000.0]
    store = _store(tmp_path, clock=lambda: clock[0], lease_seconds=5.0)
    prepared = store.prepare(OWNER, "crash-request", PLAN, identity=IDENTITY, authorized=True)
    job_id = prepared["job_id"]
    store.queue(OWNER, job_id, identity=IDENTITY, authorized=True)
    store.claim(OWNER, job_id, WORKER, IDENTITY, authorized=True)
    clock[0] += 6
    restarted = _store(tmp_path, clock=lambda: clock[0], lease_seconds=5.0)
    uncertain = restarted.status(OWNER, job_id)
    assert uncertain["job"]["state"] == "uncertain"
    assert uncertain["job"]["attempts"] == 1
    _denied(
        lambda: restarted.claim(OWNER, job_id, "replacement-worker", IDENTITY, authorized=True),
        "NOT_CLAIMABLE",
    )
    _denied(
        lambda: restarted.complete(
            OWNER,
            job_id,
            WORKER,
            1,
            IDENTITY,
            authorized=True,
            result_digest=RESULT,
        ),
        "UNCERTAIN_RESULT",
    )

    # A separate trusted reconciliation receipt may settle status but must
    # never cause a second executor claim or repeat of an unsafe action.
    settled = restarted.reconcile(
        OWNER,
        job_id,
        identity=IDENTITY,
        authorized=True,
        evidence_digest=RESULT,
        outcome="succeeded",
    )
    assert settled["state"] == "succeeded" and settled["attempts"] == 1
    assert restarted.audit(OWNER, job_id)[-2:][0]["event"] == "uncertain"
    assert restarted.audit(OWNER, job_id)[-1]["event"] == "reconciled"

    another = restarted.prepare(OWNER, "cancel-request", PLAN, identity=IDENTITY, authorized=True)
    restarted.queue(OWNER, another["job_id"], identity=IDENTITY, authorized=True)
    cancelled = restarted.cancel(OWNER, another["job_id"], identity=IDENTITY, authorized=True)
    assert cancelled["state"] == "cancelled"
    assert restarted.status(OWNER, another["job_id"])["job"]["state"] == "cancelled"

    running = restarted.prepare(OWNER, "cancel-running", PLAN, identity=IDENTITY, authorized=True)
    restarted.queue(OWNER, running["job_id"], identity=IDENTITY, authorized=True)
    restarted.claim(OWNER, running["job_id"], WORKER, IDENTITY, authorized=True)
    late_cancel = restarted.cancel(OWNER, running["job_id"], identity=IDENTITY, authorized=True)
    assert late_cancel["state"] == "uncertain"
    assert late_cancel["cancel_requested"] is True
    _denied(
        lambda: restarted.claim(
            OWNER,
            running["job_id"],
            "other-worker",
            IDENTITY,
            authorized=True,
        ),
        "NOT_CLAIMABLE",
    )


def test_t_h2d_06_bounded_owner_poll_tool_states_and_schema_never_leak_details(
    tmp_path: Path,
) -> None:
    from android_mcp_host.durable_jobs import get_job_status_schema

    store = _store(tmp_path)
    a = store.prepare(OWNER, "public-request", PLAN, identity=IDENTITY, authorized=True)

    async def check() -> None:
        async with Client(create_server()) as baseline:
            original = {t.name: t for t in await baseline.list_tools()}
        assert set(original) == {"device_status", "adb_observe", "adb_develop"}
        async with Client(create_server(durable_jobs=store, job_owner=OWNER)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*original, "host_job_status"}
            for name, prior in original.items():
                now = tools[name]
                assert (
                    prior.title,
                    prior.description,
                    prior.annotations,
                    prior.input_schema,
                    prior.output_schema,
                ) == (
                    now.title,
                    now.description,
                    now.annotations,
                    now.input_schema,
                    now.output_schema,
                )
            tool = tools["host_job_status"]
            assert tool.output_schema == get_job_status_schema()
            Draft202012Validator.check_schema(tool.output_schema)
            Draft202012Validator.check_schema(tool.input_schema)
            assert set(tool.input_schema["required"]) == {"job_id"}
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is True
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False

            reply = await client.call_tool("host_job_status", {"job_id": a["job_id"]})
            assert not reply.is_error and isinstance(reply.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(reply.structured_content)
            assert reply.structured_content["job"]["state"] == "prepared"
            wire = json.dumps(reply.structured_content)
            for private in (OWNER, IDENTITY, "public-request", str(tmp_path)):
                assert private not in wire
            assert reply.structured_content["job"]["execution_enabled"] is False
            missing = await client.call_tool("host_job_status", {"job_id": "job_" + "a" * 32})
            assert missing.structured_content["status"] == "not_found"

    asyncio.run(check())

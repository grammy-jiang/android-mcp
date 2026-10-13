"""H2.d invalid owner, worker, result, lease and status denial regressions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_host_durable_jobs import (
    IDENTITY,
    OWNER,
    PLAN,
    RESULT,
    WORKER,
    _denied,
    _store,
)

import android_mcp_host.durable_job_support as support
import android_mcp_host.durable_jobs as jobs


def prepare(store: jobs.DurableJobStore, request: str = "fixture-request-01") -> str:
    result = store.prepare(OWNER, request, PLAN, identity=IDENTITY, authorized=True)
    return str(result["job_id"])


def queued(store: jobs.DurableJobStore) -> str:
    job_id = prepare(store)
    store.queue(OWNER, job_id, identity=IDENTITY, authorized=True)
    return job_id


def running(store: jobs.DurableJobStore) -> str:
    job_id = queued(store)
    store.claim(OWNER, job_id, WORKER, IDENTITY, authorized=True)
    return job_id


def test_packaged_schema_non_object_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-durable-job-status.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(support, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        support.get_job_status_schema()


@pytest.mark.parametrize(
    "root",
    [
        Path("relative/dir"),
        Path("/tmp/../secret/dir"),
        Path("/" + "x" * 1200),
    ],
)
def test_untrusted_job_root_is_rejected(root: Path) -> None:
    _denied(lambda: jobs.DurableJobStore(root), "UNTRUSTED_ROOT")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lease_seconds": 0},
        {"lease_seconds": -1},
        {"lease_seconds": 301},
        {"lease_seconds": float("inf")},
        {"lease_seconds": float("nan")},
        {"lease_seconds": True},
        {"max_records": 0},
        {"max_records": 4097},
        {"max_records": True},
    ],
)
def test_bounded_durable_store_policy_parameters(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Invalid durable"):
        _store(tmp_path, **kwargs)


@pytest.mark.parametrize("bad", [None, 13, "", "../name", "name with space", "x" * 65])
def test_invalid_owner_not_reflected_or_stored(tmp_path: Path, bad: Any) -> None:
    store = _store(tmp_path)
    assert store.validate_owner(bad) is False
    _denied(
        lambda: store.prepare(bad, "request-valid", PLAN, identity=IDENTITY, authorized=True),
        "INVALID_OWNER",
    )
    assert store.status(bad, "job_" + "a" * 32)["status"] == "not_found"


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "now"])
def test_invalid_clock_prevents_trusted_write(tmp_path: Path, bad: Any) -> None:
    with pytest.raises(jobs.JobStoreError) as result:
        _store(tmp_path, clock=lambda: bad)
    assert result.value.code == "INVALID_CLOCK"


@pytest.mark.parametrize(
    ("request_id", "digest", "identity", "expected"),
    [
        ("", PLAN, IDENTITY, "INVALID_REQUEST"),
        ("bad!", PLAN, IDENTITY, "INVALID_REQUEST"),
        ("ab", PLAN, IDENTITY, "INVALID_REQUEST"),
        ("r" * 129, PLAN, IDENTITY, "INVALID_REQUEST"),
        ("valid-request", "b" * 63, IDENTITY, "INVALID_PLAN"),
        ("valid-request", "X" * 64, IDENTITY, "INVALID_PLAN"),
        ("valid-request", None, IDENTITY, "INVALID_PLAN"),
        ("valid-request", PLAN, "", "INVALID_IDENTITY"),
        ("valid-request", PLAN, "../other", "INVALID_IDENTITY"),
        ("valid-request", PLAN, "other target", "INVALID_IDENTITY"),
    ],
)
def test_prepare_input_validation_is_fail_closed_without_db_record(
    tmp_path: Path, request_id: Any, digest: Any, identity: Any, expected: str
) -> None:
    store = _store(tmp_path)
    _denied(
        lambda: store.prepare(OWNER, request_id, digest, identity=identity, authorized=True),
        expected,
    )
    assert store.list_status(OWNER) == []


def test_prepare_requires_trusted_true_not_truthy_authorization(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for authorization in (False, 1, None, "true"):
        _denied(
            lambda authorization=authorization: store.prepare(
                OWNER,
                "request-001",
                PLAN,
                identity=IDENTITY,
                authorized=authorization,
            ),
            "NOT_AUTHORIZED",
        )
    assert store.list_status(OWNER) == []


def test_job_count_quota_blocks_new_request_even_if_same_plan(tmp_path: Path) -> None:
    store = _store(tmp_path, max_records=2)
    prepare(store)
    store.prepare(OWNER, "another-request", PLAN, identity=IDENTITY, authorized=True)
    _denied(
        lambda: store.prepare(OWNER, "third-request", PLAN, identity=IDENTITY, authorized=True),
        "RESOURCE_LIMIT",
    )
    assert len(store.list_status(OWNER)) == 2


def test_invalid_or_duplicate_generated_tokens_cannot_create_extra_job(tmp_path: Path) -> None:
    invalid = _store(tmp_path, token_factory=lambda _: "../" * 10 + "..")
    _denied(
        lambda: invalid.prepare(OWNER, "bad-token", PLAN, identity=IDENTITY, authorized=True),
        "STORAGE_FAILURE",
    )
    fixed = _store(tmp_path, token_factory=lambda _: "z" * 32)
    first = fixed.prepare(OWNER, "first-token", PLAN, identity=IDENTITY, authorized=True)
    assert first["job_id"] == "job_" + "z" * 32
    _denied(
        lambda: fixed.prepare(OWNER, "next-token", PLAN, identity=IDENTITY, authorized=True),
        "STORAGE_FAILURE",
    )
    assert len(fixed.list_status(OWNER)) == 1


def test_queue_rejects_cross_owner_bad_identity_and_unknown_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job_id = prepare(store)
    for owner, target, identity, authorized, error in (
        (OWNER, job_id, "changed-target", True, "STALE_IDENTITY"),
        ("someone-else", job_id, IDENTITY, True, "NOT_FOUND"),
        (OWNER, "../secret", IDENTITY, True, "NOT_FOUND"),
        (OWNER, job_id, [], True, "STALE_IDENTITY"),
        (OWNER, job_id, IDENTITY, False, "NOT_AUTHORIZED"),
    ):
        _denied(
            lambda owner=owner, target=target, identity=identity, authorized=authorized: (
                store.queue(owner, target, identity=identity, authorized=authorized)
            ),
            error,
        )
    assert store.status(OWNER, job_id)["job"]["state"] == "prepared"


@pytest.mark.parametrize("worker", ["", "x/y", "x with space", "x" * 129, None, 123])
def test_worker_identity_is_validated_before_claim(tmp_path: Path, worker: Any) -> None:
    store = _store(tmp_path)
    job_id = queued(store)
    _denied(
        lambda: store.claim(OWNER, job_id, worker, IDENTITY, authorized=True),
        "INVALID_WORKER",
    )
    assert store.status(OWNER, job_id)["job"]["state"] == "queued"


def test_claim_not_authorized_or_stale_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job_id = queued(store)
    _denied(
        lambda: store.claim(OWNER, job_id, WORKER, IDENTITY),
        "NOT_AUTHORIZED",
    )
    _denied(
        lambda: store.claim(OWNER, job_id, WORKER, "changed-target", authorized=True),
        "STALE_IDENTITY",
    )
    _denied(
        lambda: store.claim("other-owner", job_id, WORKER, IDENTITY, authorized=True),
        "NOT_FOUND",
    )
    assert store.status(OWNER, job_id)["job"]["state"] == "queued"


@pytest.mark.parametrize(
    ("generation", "result_digest", "failure_code", "expected"),
    [
        (0, RESULT, None, "STALE_WORKER"),
        (True, RESULT, None, "STALE_WORKER"),
        (1, None, None, "INVALID_RESULT"),
        (1, RESULT, "FAILURE", "INVALID_RESULT"),
        (1, "xx", None, "INVALID_RESULT"),
        (1, "X" * 64, None, "INVALID_RESULT"),
        (1, None, "bad code", "INVALID_RESULT"),
        (1, None, "x", "INVALID_RESULT"),
        (1, None, 20, "INVALID_RESULT"),
    ],
)
def test_worker_result_validation_before_mutation(
    tmp_path: Path, generation: Any, result_digest: Any, failure_code: Any, expected: str
) -> None:
    store = _store(tmp_path)
    job_id = running(store)
    _denied(
        lambda: store.complete(
            OWNER,
            job_id,
            WORKER,
            generation,
            IDENTITY,
            authorized=True,
            result_digest=result_digest,
            failure_code=failure_code,
        ),
        expected,
    )
    assert store.status(OWNER, job_id)["job"]["state"] == "running"


def test_completion_rejects_stale_worker_id_generation_and_lease_expiry(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    store = _store(tmp_path, clock=lambda: clock[0], lease_seconds=4)
    job_id = running(store)
    for worker, generation, identity, reason in (
        ("changed-worker", 1, IDENTITY, "STALE_WORKER"),
        (WORKER, 2, IDENTITY, "STALE_WORKER"),
        (WORKER, 1, "other-device", "STALE_IDENTITY"),
    ):
        _denied(
            lambda worker=worker, generation=generation, identity=identity: store.complete(
                OWNER,
                job_id,
                worker,
                generation,
                identity,
                authorized=True,
                result_digest=RESULT,
            ),
            reason,
        )
    clock[0] += 5
    _denied(
        lambda: store.complete(
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
    assert store.status(OWNER, job_id)["job"]["state"] == "uncertain"
    assert store.audit(OWNER, job_id)[-1]["event"] == "uncertain"
    _denied(
        lambda: store.complete(
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


def test_recovery_replays_once_only_and_keeps_unexpired_worker(tmp_path: Path) -> None:
    clock = [10.0]
    store = _store(tmp_path, clock=lambda: clock[0], lease_seconds=2)
    job_id = running(store)
    assert store.recover() == 0
    clock[0] += 3
    assert store.recover() == 1
    assert store.recover() == 0
    assert store.status(OWNER, job_id)["job"]["state"] == "uncertain"
    assert [item["event"] for item in store.audit(OWNER, job_id)].count("uncertain") == 1


def test_running_cancel_marks_uncertain_and_no_claim_is_possible(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job_id = running(store)
    cancelled = store.cancel(OWNER, job_id, identity=IDENTITY, authorized=True)
    assert cancelled["state"] == "uncertain"
    assert cancelled["cancel_requested"] is True
    _denied(
        lambda: store.cancel(OWNER, job_id, identity=IDENTITY, authorized=True),
        "INVALID_TRANSITION",
    )
    _denied(
        lambda: store.claim(OWNER, job_id, WORKER, IDENTITY, authorized=True),
        "NOT_CLAIMABLE",
    )


def test_cancel_prepared_and_done_job_does_not_change_final_status(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    job_id = prepare(store)
    assert store.cancel(OWNER, job_id, identity=IDENTITY, authorized=True)["state"] == "cancelled"
    _denied(
        lambda: store.cancel(OWNER, job_id, identity=IDENTITY, authorized=True),
        "INVALID_TRANSITION",
    )
    _denied(
        lambda: store.queue(OWNER, job_id, identity=IDENTITY, authorized=True),
        "INVALID_TRANSITION",
    )


@pytest.mark.parametrize(
    ("evidence", "outcome", "code"),
    [
        ("bad", "succeeded", "INVALID_EVIDENCE"),
        ("X" * 64, "succeeded", "INVALID_EVIDENCE"),
        (RESULT, "not-a-state", "INVALID_OUTCOME"),
        (RESULT, "cancelled", "INVALID_OUTCOME"),
    ],
)
def test_reconciliation_bad_evidence_or_outcome_is_never_accepted(
    tmp_path: Path, evidence: str, outcome: str, code: str
) -> None:
    store = _store(tmp_path)
    job_id = running(store)
    store.cancel(OWNER, job_id, identity=IDENTITY, authorized=True)
    _denied(
        lambda: store.reconcile(
            OWNER,
            job_id,
            identity=IDENTITY,
            authorized=True,
            evidence_digest=evidence,
            outcome=outcome,
        ),
        code,
    )


def test_reconciliation_denies_wrong_owner_stale_and_untrusted_authorization(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    job_id = running(store)
    store.cancel(OWNER, job_id, identity=IDENTITY, authorized=True)
    for owner, identity, auth, expected in (
        ("someone-else", IDENTITY, True, "NOT_FOUND"),
        (OWNER, "stale-device", True, "STALE_IDENTITY"),
        (OWNER, IDENTITY, False, "NOT_AUTHORIZED"),
    ):
        _denied(
            lambda owner=owner, identity=identity, auth=auth: store.reconcile(
                owner,
                job_id,
                identity=identity,
                authorized=auth,
                evidence_digest=RESULT,
                outcome="failed",
            ),
            expected,
        )
    failed = store.reconcile(
        OWNER,
        job_id,
        identity=IDENTITY,
        authorized=True,
        evidence_digest=RESULT,
        outcome="failed",
    )
    assert failed["state"] == "failed" and failed["result_digest"] is None


def test_no_reconcile_from_prepared_or_completed_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job_id = prepare(store)
    _denied(
        lambda: store.reconcile(
            OWNER,
            job_id,
            identity=IDENTITY,
            authorized=True,
            evidence_digest=RESULT,
            outcome="succeeded",
        ),
        "INVALID_TRANSITION",
    )


def test_unknown_owner_poll_and_audit_have_no_owner_information(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job_id = prepare(store)
    unknown = store.status("another-owner", job_id)
    malformed = store.status("../other", job_id)
    invalid = store.status(OWNER, "job_../../../etc/passwd")
    assert unknown == malformed == invalid
    assert json.dumps(unknown).count("NOT_FOUND") == 1
    _denied(lambda: store.audit("another-owner", job_id), "NOT_FOUND")


def test_sqlite_failure_is_typed_and_does_not_reflect_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    with monkeypatch.context() as scoped:

        def failed_connection(*args: Any, **kwargs: Any) -> Any:
            raise sqlite3.OperationalError("SECRET PRIVATE DB ERROR")

        scoped.setattr(jobs.sqlite3, "connect", failed_connection)
        _denied(
            lambda: store.prepare(OWNER, "request-error", PLAN, identity=IDENTITY, authorized=True),
            "STORAGE_FAILURE",
        )
        assert store.status(OWNER, "job_" + "a" * 32)["status"] == "not_found"

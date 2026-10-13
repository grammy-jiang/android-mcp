"""H3.d cancellation must be constrained to the originating snapshot plan."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_snapshot_manager import REQ, SNAP, fixture

from android_mcp_host.durable_job_support import JobStoreError


def test_snapshot_cancel_cannot_cancel_an_unrelated_host_lifecycle_job(
    tmp_path: Path,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    unrelated = jobs.prepare(
        OWNER,
        "lifecycle-owned-worker",
        "a" * 64,
        identity=handle,
        authorized=True,
    )
    jobs.queue(OWNER, unrelated["job_id"], identity=handle, authorized=True)
    jobs.claim(
        OWNER,
        unrelated["job_id"],
        "host-emulator-worker",
        handle,
        authorized=True,
    )
    before = jobs.status(OWNER, unrelated["job_id"])["job"]["state"]
    assert before == "running"
    denied = manager.operate("cancel", NAME, handle, SNAP, job_id=unrelated["job_id"])
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
    after = jobs.status(OWNER, unrelated["job_id"])["job"]["state"]
    assert after == "running"


def test_restore_and_delete_idempotency_binds_exact_snapshot_handle(
    tmp_path: Path,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    first = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert first["status"] == "created"
    original = first["snapshot"]["handle"]
    forged = "mcpsnap_" + "z" * 32
    restored = manager.operate(
        "restore",
        NAME,
        handle,
        SNAP,
        snapshot_handle=original,
        request_id="restore-bound-request",
    )
    assert restored["status"] == "simulated"
    bad_replay = manager.operate(
        "restore",
        NAME,
        handle,
        SNAP,
        snapshot_handle=forged,
        request_id="restore-bound-request",
    )
    assert bad_replay["status"] == "blocked"
    assert bad_replay["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    bad_delete = manager.operate(
        "delete",
        NAME,
        handle,
        SNAP,
        snapshot_handle=forged,
        request_id="delete-bound-request",
    )
    assert bad_delete["status"] == "blocked"
    valid_delete_replay = manager.operate(
        "delete",
        NAME,
        handle,
        SNAP,
        snapshot_handle=original,
        request_id="delete-bound-request",
    )
    assert valid_delete_replay["status"] == "blocked"
    assert valid_delete_replay["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(manager.operate("list", NAME, handle)["snapshots"]) == 1


def test_cancel_requires_job_id_exact_snapshot_name_and_bounded_handle(
    tmp_path: Path,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    without_id = manager.operate("cancel", NAME, handle, SNAP)
    assert without_id["status"] == "blocked"
    assert without_id["errors"][0]["code"] == "JOB_UNAVAILABLE"
    unknown = manager.operate("cancel", NAME, handle, SNAP, job_id="job_" + "x" * 32)
    assert unknown["status"] == "blocked"
    assert unknown["errors"][0]["code"] == "JOB_UNAVAILABLE"
    wrong_handle = manager.operate(
        "cancel",
        NAME,
        handle,
        SNAP,
        snapshot_handle="invalid path",
        job_id="job_" + "x" * 32,
    )
    assert wrong_handle["status"] == "blocked"
    assert wrong_handle["errors"][0]["code"] == "INVALID_HANDLE"
    assert jobs.list_status(OWNER) == []


def test_completed_snapshot_job_cannot_be_cancelled_or_reopened(
    tmp_path: Path,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    completed = manager.operate("create", NAME, handle, SNAP, request_id=REQ)
    assert completed["status"] == "created"
    response = manager.operate("cancel", NAME, handle, SNAP, job_id=completed["job_id"])
    assert response["status"] == "blocked"
    assert response["errors"][0]["code"] == "JOB_UNAVAILABLE"
    assert jobs.status(OWNER, completed["job_id"])["job"]["state"] == "succeeded"


def test_snapshot_cancel_failure_preserves_uncertain_journal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, handle, jobs = fixture(tmp_path)
    owned = manager.provisioner.verify_owned(NAME, handle)
    assert owned is not None
    digest = manager._plan_digest("create", owned, SNAP)
    created = jobs.prepare(OWNER, REQ, digest, identity=handle, authorized=True)
    jobs.queue(OWNER, created["job_id"], identity=handle, authorized=True)
    jobs.claim(OWNER, created["job_id"], "snapshot-fixture-worker", handle, authorized=True)
    with monkeypatch.context() as patch:
        patch.setattr(
            jobs,
            "cancel",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
        )
        response = manager.operate("cancel", NAME, handle, SNAP, job_id=created["job_id"])
    assert response["status"] == "uncertain"
    assert response["job_id"] == created["job_id"]
    assert jobs.status(OWNER, created["job_id"])["job"]["state"] == "running"
    assert (
        manager.operate("create", NAME, handle, "snap_later", request_id="later-create")["status"]
        == "blocked"
    )

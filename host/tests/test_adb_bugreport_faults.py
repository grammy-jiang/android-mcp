"""H5.a exact-owner approval, unsafe frame and recovery denial tests."""

from __future__ import annotations

import math
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_bugreport_artifacts import (
    ART_OWNER,
    MARKER,
    NAME,
    OWNER,
    archive,
    builder,
    collect,
)

import android_mcp_host.synthetic_bugreport as module
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_bugreport import (
    BugreportApproval,
    BugreportFrame,
    BugreportService,
)


def good_frame(handle: str, lid: str) -> BugreportFrame:
    return BugreportFrame(archive(), MARKER, NAME, handle, lid, True, True)


@pytest.mark.parametrize(
    "fields",
    [
        {"owner": "foreign"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "x" * 32},
        {"purpose": "other"},
        {"valid_until_epoch": 0},
        {"valid_until_epoch": True},
        {"valid_until_epoch": time.time() + 600},
        {"valid_until_epoch": math.nan},
        {"valid_until_epoch": math.inf},
        {"valid_until_epoch": "bad"},
        {"ttl_s": 0},
        {"ttl_s": 301},
        {"ttl_s": True},
        {"ttl_s": 120.5},
        {"ttl_s": "long"},
    ],
)
def test_t_h5a_02_invalid_approval_never_reaches_private_reader(
    tmp_path: Path,
    fields: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    assert worker._approval is not None
    worker._approval = replace(worker._approval, **fields)
    worker._fixture = lambda *args: pytest.fail("Reader executed without grant")
    try:
        denied = collect(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert len(jobs.list_status(OWNER)) == 1
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"avd_name": "foreign"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "x" * 32},
        {"complete": False},
        {"complete": "true"},
        {"synthetic": False},
        {"synthetic": "true"},
        {"status_line": "OK:/data/data/private.zip"},
        {"status_line": None},
        {"payload": "fake bytes"},
    ],
)
def test_t_h5a_03_spoofed_marker_target_state_or_media_type_fail_closed(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    worker._fixture = lambda *args: replace(good_frame(handle, lid), **change)
    try:
        response = collect(worker, handle, lid)
        assert response["status"] == "failed"
        assert response["errors"][0]["code"] == "BAD_FRAME"
        assert response["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "failed"
        assert collect(worker, handle, lid)["status"] == "failed"
    finally:
        live.shutdown()


def test_constructor_rejects_foreign_owner_or_invalid_artifact_owner(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    try:
        for owner, artifact_owner in (
            ("foreign", ART_OWNER),
            (OWNER, "../../private"),
            ("..", ART_OWNER),
        ):
            with pytest.raises(ValueError):
                BugreportService(
                    live.provisioner,
                    live,
                    jobs,
                    store,
                    owner=owner,
                    artifact_owner=artifact_owner,
                )
    finally:
        live.shutdown()


def test_production_has_no_collector_even_with_fake_approval(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    worker._fixture = None
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_missing_live_lifecycle_does_not_call_collector(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    live.shutdown()
    worker._fixture = lambda *args: pytest.fail("Disconnected synthetic device executed")
    result = collect(worker, handle, lid)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"


def test_lifecycle_lost_during_collection_marks_uncertain_not_success(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)

    def disconnect(*args: Any) -> BugreportFrame:
        live.shutdown()
        return good_frame(handle, lid)

    worker._fixture = disconnect
    result = collect(worker, handle, lid)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert store.list_metadata(ART_OWNER) == []
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"


def test_approval_expires_during_report_before_private_storage(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    timebox = [1000.0]
    worker._clock = lambda: timebox[0]
    worker._approval = BugreportApproval(
        OWNER,
        handle,
        lid,
        "synthetic-sanitized-bugreport",
        1010.0,
        120,
    )

    def expire(*args: Any) -> BugreportFrame:
        timebox[0] = 1011
        return good_frame(handle, lid)

    worker._fixture = expire
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_faulty_clock_cannot_authorize_private_collection(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    worker._clock = lambda: (_ for _ in ()).throw(ValueError("PRIVATE-CLOCK"))
    worker._fixture = lambda *args: pytest.fail("Invalid grant clock enabled read")
    try:
        reply = collect(worker, handle, lid)
        assert reply["status"] == "blocked"
        assert reply["errors"][0]["code"] == "CONSENT_REQUIRED"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (subprocess.TimeoutExpired(["fake-bugreport"], 0.01), "TIMEOUT"),
        (OSError("PRIVATE-HOST-PATH"), "RUNNER_FAILED"),
        (RuntimeError("PRIVATE-STATE"), "RUNNER_FAILED"),
        (subprocess.CalledProcessError(3, ["fake-bugreport"]), "RUNNER_FAILED"),
    ],
)
def test_t_h5a_05_runner_faults_are_typed_and_without_paths(
    tmp_path: Path,
    exception: Exception,
    reason: str,
) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)

    def failed(*args: Any) -> BugreportFrame:
        raise exception

    worker._fixture = failed
    try:
        response = collect(worker, handle, lid)
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == reason
        assert "PRIVATE-" not in str(response)
        assert response["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_busy_fixture_lock_and_private_job_error_deny_before_collect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    worker._fixture = lambda *args: pytest.fail("Busy untrusted collector called")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "claim_fixture_lock", lambda *args: None)
            assert collect(worker, handle, lid)["errors"][0]["code"] == "RECOVERY_REQUIRED"
        with monkeypatch.context() as patch:

            def unavailable(*args: Any) -> Any:
                raise OSError("PRIVATE-LOCK")

            patch.setattr(module, "claim_fixture_lock", unavailable)
            assert collect(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        with monkeypatch.context() as patch:

            def unavailable_store(*args: Any, **kwargs: Any) -> Any:
                raise JobStoreError("STORAGE_FAILURE")

            patch.setattr(jobs, "lookup_request", unavailable_store)
            assert collect(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_other_uncertain_job_blocks_collection_before_any_reader(tmp_path: Path) -> None:
    import hashlib

    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    stale = jobs.prepare(
        OWNER,
        "other-uncertain-diagnostic",
        hashlib.sha256(b"private-unknown").hexdigest(),
        identity=handle,
        authorized=True,
    )
    worker._fixture = lambda *args: pytest.fail("Other uncertain job must fence capture")
    try:
        denied = collect(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "RECOVERY_REQUIRED"
        assert stale["job_id"] != lid
    finally:
        live.shutdown()


def test_invalid_action_and_request_are_typed_denials(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, _ = builder(tmp_path)
    try:
        for action in ("shell", "delete", ["collect"], None):
            response = worker.submit(action, NAME, handle, lid, request_id="bad")
            assert response["status"] == "blocked"
            assert response["errors"][0]["code"] == "INVALID_ACTION"
        for rid in (None, "", "../foreign", "\nunsafe"):
            assert (
                worker.submit("collect", NAME, handle, lid, request_id=rid)["errors"][0]["code"]
                == "INVALID_INPUT"
            )
        assert worker.submit("plan", NAME, handle, lid)["status"] == "planned"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()

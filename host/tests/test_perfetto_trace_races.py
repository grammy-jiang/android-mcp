"""H5.c two-phase private trace commit, owner fence and failure injection."""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import OWNER
from test_perfetto_trace_job import ART_OWNER, builder, submit

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.synthetic_perfetto import PerfettoService


def test_constructor_denies_owner_impersonation_and_private_artifact_mismatch(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        for owner, artifact_owner in [
            ("other-owner", ART_OWNER),
            (OWNER, "invalid owner with spaces"),
        ]:
            with pytest.raises(ValueError, match="owner"):
                PerfettoService(
                    live.provisioner,
                    live,
                    jobs,
                    store,
                    owner=owner,
                    artifact_owner=artifact_owner,
                )
    finally:
        live.shutdown()


def test_missing_grant_and_invalid_clock_denied_without_running(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        worker._clock = lambda: object()
        response = submit(worker, handle, lid, "capture")
        assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
        worker._signal_stop("job_" + "x" * 32)
        worker._clock = time.time
        worker._approval = None
        response = submit(worker, handle, lid, "capture")
        assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert calls == []
    finally:
        live.shutdown()


def test_pending_other_job_blocks_capture_before_fixture(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        jobs.prepare(
            OWNER,
            "other-recovery",
            "a" * 64,
            identity=handle,
            authorized=True,
        )
        denied = submit(worker, handle, lid, "capture")
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "RECOVERY_REQUIRED"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize("failure", ["oserror", "unavailable"])
def test_fake_avd_lock_failure_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import android_mcp_host.synthetic_perfetto as module

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any) -> Any:
        if failure == "oserror":
            raise OSError("untrusted private lock")
        return None

    monkeypatch.setattr(module, "claim_fixture_lock", fail)
    try:
        response = submit(worker, handle, lid, "capture")
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == (
            "JOB_UNAVAILABLE" if failure == "oserror" else "RECOVERY_REQUIRED"
        )
        assert calls == []
    finally:
        live.shutdown()


def test_durable_job_prepare_error_does_not_call_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "prepare", fail)
    try:
        denied = submit(worker, handle, lid, "capture")
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert calls == []
    finally:
        live.shutdown()


def test_callback_exceeded_deadline_cannot_confirm_success(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original = worker._fixture

    def delay(*args: Any) -> Any:
        time.sleep(3.02)
        assert original is not None
        return original(*args)

    worker._fixture = delay
    try:
        result = submit(worker, handle, lid, "capture")
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize("post_put", ["cancel", "disconnect", "revoke"])
def test_durable_two_phase_commit_rechecks_auth_and_revokes_both_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_put: str,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original = store.put
    puts = [0]

    def override(*args: Any, **kwargs: Any) -> Any:
        saved = original(*args, **kwargs)
        puts[0] += 1
        if puts[0] == 2:
            if post_put == "cancel":
                for stop in worker._active.values():
                    stop.set()
            elif post_put == "disconnect":
                live.shutdown()
            elif post_put == "revoke":
                assert worker._approval is not None
                worker._approval = replace(worker._approval, valid_until_epoch=0.0)
        return saved

    monkeypatch.setattr(store, "put", override)
    try:
        result = submit(worker, handle, lid, "capture")
        assert result["status"] == "uncertain"
        assert (
            result["errors"][0]["code"]
            == {
                "cancel": "CANCELLED",
                "disconnect": "UNVERIFIED_TARGET",
                "revoke": "CONSENT_REQUIRED",
            }[post_put]
        )
        assert puts == [2]
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_receipt_second_artifact_write_failure_does_not_leave_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original = store.put
    count = [0]

    def fail(*args: Any, **kwargs: Any) -> Any:
        count[0] += 1
        if count[0] == 2:
            raise ArtifactStoreError("STORAGE_FAILURE")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "put", fail)
    try:
        result = submit(worker, handle, lid, "capture")
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
        assert count == [2]
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_failure_cleanup_handles_private_revoke_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original_put = store.put
    count = [0]

    def partial(*args: Any, **kwargs: Any) -> Any:
        count[0] += 1
        if count[0] == 2:
            raise ArtifactStoreError("TEST_FAILURE")
        return original_put(*args, **kwargs)

    def revoked(*args: Any, **kwargs: Any) -> None:
        raise ArtifactStoreError("TEST_REVOKE_FAILURE")

    monkeypatch.setattr(store, "put", partial)
    monkeypatch.setattr(store, "revoke", revoked)
    try:
        result = submit(worker, handle, lid, "capture")
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
    finally:
        live.shutdown()


def test_failure_cleanup_catches_job_cancel_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    def fixture(*args: Any) -> Any:
        raise RuntimeError("disposable synthetic fixture")

    worker._fixture = fixture
    monkeypatch.setattr(jobs, "cancel", fail)
    try:
        result = submit(worker, handle, lid, "capture")
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
    finally:
        live.shutdown()


def test_expired_private_receipt_cannot_be_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        trace = submit(worker, handle, lid, "capture")
        assert trace["status"] == "ok"
        store.revoke(ART_OWNER, trace["artifact_handle"])
        result = submit(worker, handle, lid, "capture")
        assert result["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_frames_profile_private_digest_records_fixed_provenance(tmp_path: Path) -> None:
    from android_mcp_host.perfetto_trace_support import MARKER

    raw = (
        MARKER
        + b"ts_ms=0;event=frame_present;value=1\n"
        + b"ts_ms=100;event=frame_dropped;value=2\n"
    )
    worker, live, jobs, store, handle, lid, calls = builder(
        tmp_path,
        profile="frames-lite-v1",
        payload=raw,
    )
    try:
        result = submit(worker, handle, lid, "capture", profile="frames-lite-v1")
        assert result["status"] == "ok"
        assert result["profile"] == "frames-lite-v1"
        assert len(calls) == 1
        assert result["sample_count"] == 2
        assert len(store.read(ART_OWNER, result["artifact_handle"])) == result["size_bytes"]
        assert (
            hashlib.sha256(store.read(ART_OWNER, result["artifact_handle"])).hexdigest()
            == result["sha256"]
        )
    finally:
        live.shutdown()

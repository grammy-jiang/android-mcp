"""H4.c durable cancellation, partial-write rollback and private replay tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from test_adb_screenrecord_job import (
    ART_OWNER,
    MAX_VIDEO,
    REQ,
    builder,
    mp4_fixture,
    record,
)
from test_avd_provisioning import NAME, OWNER

import android_mcp_host.synthetic_screenrecord as media
from android_mcp_host.command_runner import bounded_run
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError
from android_mcp_host.synthetic_screenrecord import RecordedClip


def cancel(worker: Any, handle: str, lid: str, job_id: str, request: str = REQ) -> dict[str, Any]:
    return worker.submit(
        "cancel",
        NAME,
        handle,
        lid,
        request_id=request,
        job_id=job_id,
        duration_s=5,
        display_id=0,
        codec="h264",
        max_bytes=MAX_VIDEO,
    )


def test_cancel_running_fixture_is_cooperative_and_prevents_artifact_commit(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    released = threading.Event()
    result: dict[str, Any] = {}
    events: list[bool] = []

    def recorder(
        name: str,
        handle: str,
        lid: str,
        duration: int,
        display: int,
        codec: str,
        limit: int,
        stop: threading.Event,
    ) -> RecordedClip:
        entered.set()
        assert stop.wait(3), "Cancel must signal running bounded fixture"
        events.append(stop.is_set())
        released.set()
        return RecordedClip(
            mp4_fixture(), name, handle, lid, duration, display, codec, False, False, True
        )

    worker, live, jobs, artifacts, handle, lid = builder(tmp_path, backend=recorder)
    thread = threading.Thread(
        target=lambda: result.update(record(worker, handle, lid)), daemon=True
    )
    try:
        thread.start()
        assert entered.wait(4)
        active = [
            row
            for row in jobs.list_status(OWNER)
            if row["job_id"] != lid and row["state"] == "running"
        ]
        assert len(active) == 1
        jid = active[0]["job_id"]
        halted = cancel(worker, handle, lid, jid)
        assert halted["status"] == "uncertain"
        assert halted["errors"][0]["code"] == "CANCELLED"
        assert released.wait(4)
        thread.join(4)
        assert not thread.is_alive()
        assert events == [True]
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CANCELLED"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, jid)["job"]["state"] == "uncertain"
        duplicate = record(worker, handle, lid)
        assert duplicate["job_id"] == jid
        assert duplicate["status"] == "uncertain"
        assert cancel(worker, handle, lid, jid)["status"] == "uncertain"
    finally:
        live.shutdown()


def test_synthetic_video_subprocess_timeout_kills_private_child(tmp_path: Path) -> None:
    script = tmp_path / "private-fake-recorder.py"
    pidfile = tmp_path / "fake-pid.txt"
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(45)\n",
        encoding="utf-8",
    )
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)

    def hanging(*args: Any) -> Any:
        bounded_run([sys.executable, str(script), str(pidfile)], 0.6, 1024)
        raise AssertionError("Unexpected synthetic process completed")

    worker._fixture = hanging
    try:
        output = record(worker, handle, lid)
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "TIMEOUT"
        assert pidfile.exists()
        childpid = int(pidfile.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(childpid, 0)
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, output["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_cancel_unknown_job_or_changed_request_is_typed_and_sideload_free(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    unknown = "job_" + "x" * 32
    try:
        assert cancel(worker, handle, lid, unknown)["errors"][0]["code"] == "NOT_ACTIVE"
        assert jobs.list_status(OWNER)[0]["job_id"] == lid
        recorded = record(worker, handle, lid)
        assert recorded["status"] == "ok"
        assert cancel(worker, handle, lid, recorded["job_id"])["errors"][0]["code"] == "NOT_ACTIVE"
        altered = cancel(worker, handle, lid, recorded["job_id"], request="changed-request")
        assert altered["status"] == "blocked"
        assert altered["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert jobs.status(OWNER, recorded["job_id"])["job"]["state"] == "succeeded"
        assert artifacts.read(ART_OWNER, recorded["artifact_handle"]) == mp4_fixture()
    finally:
        live.shutdown()


def test_failed_second_private_write_revokes_video_and_never_completes_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    original = artifacts.put
    attempts = [0]

    def fault(owner: str, content: bytes, **kwargs: Any) -> dict[str, Any]:
        attempts[0] += 1
        if attempts[0] == 2:
            raise ArtifactStoreError("QUOTA_EXCEEDED")
        return original(owner, content, **kwargs)

    monkeypatch.setattr(artifacts, "put", fault)
    try:
        result = record(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
        assert attempts == [2]
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_failed_last_job_receipt_completion_revokes_video_and_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    with monkeypatch.context() as patch:

        def fail_complete(*args: Any, **kwargs: Any) -> Any:
            raise JobStoreError("STORAGE_FAILURE")

        patch.setattr(jobs, "complete", fail_complete)
        try:
            result = record(worker, handle, lid)
            assert result["status"] == "uncertain"
            assert result["errors"][0]["code"] == "RUNNER_FAILED"
            assert artifacts.list_metadata(ART_OWNER) == []
            assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        finally:
            live.shutdown()


def test_failed_cleanup_revoke_is_handled_without_exposing_private_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    count = [0]
    real = artifacts.put

    def partial(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        count[0] += 1
        if count[0] == 2:
            raise ArtifactStoreError("STORAGE_FAILURE")
        return real(owner, data, **kwargs)

    monkeypatch.setattr(artifacts, "put", partial)

    def fail_revoke(*args: Any) -> Any:
        raise ArtifactStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(artifacts, "revoke", fail_revoke)
    try:
        outcome = record(worker, handle, lid)
        assert outcome["status"] == "uncertain"
        assert "STORAGE_FAILURE" not in json.dumps(outcome)
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_job_store_initial_failure_and_busy_lock_block_before_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: pytest.fail("Unapproved fixture execution")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(media, "claim_fixture_lock", lambda *args: None)
            assert record(worker, handle, lid)["errors"][0]["code"] == "RECOVERY_REQUIRED"
        with monkeypatch.context() as patch:

            def unavailable(*args: Any) -> Any:
                raise OSError("PRIVATE-LOCK-FILE")

            patch.setattr(media, "claim_fixture_lock", unavailable)
            assert record(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        with monkeypatch.context() as patch:

            def unavailable_store(*args: Any) -> Any:
                raise JobStoreError("STORAGE_FAILURE")

            patch.setattr(jobs, "lookup_request", unavailable_store)
            assert record(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_recovery_required_if_preexisting_other_uncertain_job_not_retried(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    data = jobs.prepare(
        OWNER,
        "prior-stale-job",
        hashlib.sha256(b"private-plan").hexdigest(),
        identity=handle,
        authorized=True,
    )
    try:
        result = record(worker, handle, lid)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "RECOVERY_REQUIRED"
        assert len(jobs.list_status(OWNER)) == 2
        assert data["job_id"] not in worker._active
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_recorder_runtime_error_is_generic_and_cancelled_durable(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    worker._fixture = lambda *args: (_ for _ in ()).throw(
        subprocess.CalledProcessError(3, ["fake-video-child"], output=b"PRIVATE")
    )
    try:
        response = record(worker, handle, lid)
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "RUNNER_FAILED"
        assert "PRIVATE" not in json.dumps(response)
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_approval_clock_failure_and_bad_ttl_never_record(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    worker._clock = lambda: (_ for _ in ()).throw(ValueError("private-invalid-clock"))
    worker._fixture = lambda *args: pytest.fail("Clock failure cannot enable capture")
    try:
        result = record(worker, handle, lid)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_forced_recording_expiry_after_artifact_write_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid = builder(tmp_path)
    approved = [0]
    real = worker._approved

    def expires(handle: str, lid: str) -> bool:
        approved[0] += 1
        if approved[0] == 3:
            return False
        return real(handle, lid)

    monkeypatch.setattr(worker, "_approved", expires)
    try:
        outcome = record(worker, handle, lid)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "CANCELLED"
        assert approved == [3]
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()

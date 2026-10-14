"""H4.e scoped durable cancel, partial mutation and subprocess timeout tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from test_adb_file_push_policy import (
    ART_OWNER,
    DATA,
    DEST,
    MIME,
    REQ,
    SHA,
    builder,
    run_push,
)
from test_avd_provisioning import NAME, OWNER

from android_mcp_host.command_runner import bounded_run
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_file_push import PushFrame


def cancel(
    worker: Any, handle: str, lid: str, token: str, jid: str, request: str = REQ
) -> dict[str, Any]:
    return worker.submit(
        "cancel",
        NAME,
        handle,
        lid,
        token,
        SHA,
        DEST,
        mime_type=MIME,
        request_id=request,
        job_id=jid,
    )


def test_cancel_running_fixture_signals_stop_and_records_uncertainty(tmp_path: Path) -> None:
    active = threading.Event()
    done = threading.Event()
    answer: dict[str, Any] = {}
    writes = [0]

    def slow(
        name: str,
        handle: str,
        lid: str,
        package: str,
        dest: str,
        payload: bytes,
        cap: int,
        stop: threading.Event,
    ) -> PushFrame:
        active.set()
        assert stop.wait(4), "Cancellation must signal fixture"
        assert stop.is_set()
        writes[0] += 1
        done.set()
        return PushFrame(
            name, handle, lid, package, dest, SHA, len(payload), True, True, False, False, True
        )

    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path, writer=slow)
    thread = threading.Thread(
        target=lambda: answer.update(run_push(worker, handle, lid, token)), daemon=True
    )
    try:
        thread.start()
        assert active.wait(4)
        executing = [
            j for j in jobs.list_status(OWNER) if j["job_id"] != lid and j["state"] == "running"
        ]
        assert len(executing) == 1
        jid = executing[0]["job_id"]
        stopped = cancel(worker, handle, lid, token, jid)
        assert stopped["status"] == "uncertain"
        assert stopped["errors"][0]["code"] == "CANCELLED"
        assert done.wait(4)
        thread.join(4)
        assert not thread.is_alive()
        assert writes == [1]
        assert answer["status"] == "uncertain"
        assert answer["errors"][0]["code"] == "CANCELLED"
        assert jobs.status(OWNER, jid)["job"]["state"] == "uncertain"
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert run_push(worker, handle, lid, token)["job_id"] == jid
        assert cancel(worker, handle, lid, token, jid)["status"] == "uncertain"
        assert fs == {}
    finally:
        live.shutdown()


def test_cancel_wrong_job_does_not_mutate_other_work_or_prior_success(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    try:
        unknown = cancel(worker, handle, lid, token, "job_" + "x" * 32)
        assert unknown["status"] == "blocked"
        assert unknown["errors"][0]["code"] == "NOT_ACTIVE"
        first = run_push(worker, handle, lid, token)
        assert first["status"] == "simulated"
        terminal = cancel(worker, handle, lid, token, first["job_id"])
        assert terminal["errors"][0]["code"] == "NOT_ACTIVE"
        bad_req = cancel(worker, handle, lid, token, first["job_id"], "changed-request")
        assert bad_req["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "job_id",
    [
        None,
        "bad job id",
        "job_" + "a" * 31,
        "job_" + "a" * 33,
    ],
)
def test_invalid_cancel_request_fields_fail_before_any_writer(tmp_path: Path, job_id: Any) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    worker._writer = lambda *args: pytest.fail("Wrong cancellation reached writer")
    try:
        denied = worker.submit(
            "cancel",
            NAME,
            handle,
            lid,
            token,
            SHA,
            DEST,
            mime_type=MIME,
            request_id=REQ,
            job_id=job_id,
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_cancelled_after_receipt_write_revokes_uncommitted_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    real = store.put
    calls = [0]

    def signal_during_write(owner: str, content: bytes, **kwargs: Any) -> dict[str, Any]:
        record = real(owner, content, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            assert len(worker._active) == 1
            next(iter(worker._active.values())).set()
        return record

    monkeypatch.setattr(store, "put", signal_during_write)
    try:
        result = run_push(worker, handle, lid, token)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CANCELLED"
        assert result["report_handle"] is None
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        assert fs == {DEST: DATA}  # synthetic write happened before cancellation
    finally:
        live.shutdown()


def test_job_cancel_error_return_typed_denial_without_exception_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)
    first = run_push(worker, handle, lid, token)
    assert first["status"] == "simulated"

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("SECRET-DB")

    monkeypatch.setattr(jobs, "lookup_request", fail)
    try:
        result = cancel(worker, handle, lid, token, first["job_id"])
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert "SECRET" not in json.dumps(result)
    finally:
        live.shutdown()


def test_hung_fake_subprocess_times_out_and_is_reaped(tmp_path: Path) -> None:
    script = tmp_path / "hung-synthetic-file-writer.py"
    pidfile = tmp_path / "child-pid"
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(40)\n",
        encoding="utf-8",
    )

    def hanging(*args: Any) -> PushFrame:
        bounded_run([sys.executable, str(script), str(pidfile)], 0.6, 1024)
        pytest.fail("Fixture subprocess unexpectedly completed")

    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path, writer=hanging)
    try:
        response = run_push(worker, handle, lid, token)
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "TIMEOUT"
        assert pidfile.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        assert len(store.list_metadata(ART_OWNER)) == 1
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_durable_rollback_errors_cannot_expose_private_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)

    def bad_writer(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["test-only"], 0.01)

    worker._writer = bad_writer

    def cancel_fail(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("SECRET-STATE")

    monkeypatch.setattr(jobs, "cancel", cancel_fail)
    try:
        failed = run_push(worker, handle, lid, token)
        assert failed["status"] == "uncertain"
        assert failed["errors"][0]["code"] == "TIMEOUT"
        assert "SECRET-STATE" not in json.dumps(failed)
        assert len(store.list_metadata(ART_OWNER)) == 1
    finally:
        live.shutdown()

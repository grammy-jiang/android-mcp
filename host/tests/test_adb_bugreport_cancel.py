"""H5.a cooperative cancellation and bounded fake diagnostic child cleanup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from test_adb_bugreport_artifacts import (
    ART_OWNER,
    MARKER,
    NAME,
    OWNER,
    REQ,
    archive,
    builder,
    collect,
)

from android_mcp_host.command_runner import bounded_run
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_bugreport import BugreportFrame


def cancel(worker: Any, handle: str, lid: str, job_id: str, request: str = REQ) -> dict[str, Any]:
    return worker.submit(
        "cancel",
        NAME,
        handle,
        lid,
        request_id=request,
        job_id=job_id,
    )


def test_t_h5a_05_cancel_running_collector_and_fence_private_receipt(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    stopped = threading.Event()
    answer: dict[str, Any] = {}
    calls = [0]

    def fake(
        name: str,
        handle: str,
        lid: str,
        timeout: float,
        cap: int,
        stop: threading.Event,
    ) -> BugreportFrame:
        calls[0] += 1
        entered.set()
        assert stop.wait(5)
        stopped.set()
        return BugreportFrame(archive(), MARKER, name, handle, lid, True, True)

    worker, live, jobs, store, handle, lid, _ = builder(tmp_path, runner=fake)
    thread = threading.Thread(
        target=lambda: answer.update(collect(worker, handle, lid)),
        daemon=True,
    )
    try:
        thread.start()
        assert entered.wait(5)
        active = [
            row
            for row in jobs.list_status(OWNER)
            if row["job_id"] != lid and row["state"] == "running"
        ]
        assert len(active) == 1
        jid = active[0]["job_id"]
        denied = cancel(worker, handle, lid, jid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "CANCELLED"
        assert stopped.wait(5)
        thread.join(5)
        assert not thread.is_alive()
        assert answer["status"] == "uncertain"
        assert answer["errors"][0]["code"] == "CANCELLED"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, jid)["job"]["state"] == "uncertain"
        assert calls == [1]
        assert collect(worker, handle, lid)["job_id"] == jid
        assert calls == [1]
        assert cancel(worker, handle, lid, jid)["status"] == "uncertain"
    finally:
        live.shutdown()


def test_cancel_unknown_finished_or_changed_request_cannot_delete_report(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        absent = cancel(worker, handle, lid, "job_" + "x" * 32)
        assert absent["status"] == "blocked"
        assert absent["errors"][0]["code"] == "NOT_ACTIVE"
        first = collect(worker, handle, lid)
        assert first["status"] == "ok"
        done = cancel(worker, handle, lid, first["job_id"])
        assert done["status"] == "blocked"
        assert done["errors"][0]["code"] == "NOT_ACTIVE"
        conflict = cancel(worker, handle, lid, first["job_id"], request="different-request")
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert store.public_metadata(ART_OWNER, first["artifact_handle"])["status"] == "ok"
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize("jid", [None, "bad", "job_" + "a" * 31, "job_" + "a" * 33])
def test_cancel_invalid_job_id_never_mutates_other_jobs(
    tmp_path: Path,
    jid: Any,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        denied = worker.submit("cancel", NAME, handle, lid, request_id=REQ, job_id=jid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_stop_arriving_after_two_private_writes_revokes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original = store.put
    writes = [0]

    def inject(owner: str, payload: bytes, **kw: Any) -> dict[str, Any]:
        row = original(owner, payload, **kw)
        writes[0] += 1
        if writes[0] == 2:
            assert len(worker._active) == 1
            next(iter(worker._active.values())).set()
        return row

    monkeypatch.setattr(store, "put", inject)
    try:
        reply = collect(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "CANCELLED"
        assert writes == [2]
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_hung_synthetic_bugreport_subprocess_is_killed_and_reaped(
    tmp_path: Path,
) -> None:
    script = tmp_path / "fake-bugreport-hung.py"
    pidfile = tmp_path / "synthetic-child-pid"
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(50)\n",
        encoding="utf-8",
    )

    def hung(*args: Any) -> BugreportFrame:
        bounded_run([sys.executable, str(script), str(pidfile)], 0.6, 1024)
        pytest.fail("Hung synthetic diagnostic returned unexpectedly")

    worker, live, jobs, store, handle, lid, _ = builder(tmp_path, runner=hung)
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        assert pidfile.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_job_store_cancel_failure_does_not_leak_internal_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    first = collect(worker, handle, lid)

    def error(*args: Any, **kw: Any) -> Any:
        raise JobStoreError("SECRET-DB")

    monkeypatch.setattr(jobs, "lookup_request", error)
    try:
        result = cancel(worker, handle, lid, first["job_id"])
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert "SECRET" not in json.dumps(result)
    finally:
        live.shutdown()


def test_cancel_rollback_job_error_does_not_echo_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def timeout(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fixture"], 0.1)

    worker._fixture = timeout

    def broken(*args: Any, **kw: Any) -> Any:
        raise JobStoreError("SECRET-CANCEL-PATH")

    monkeypatch.setattr(jobs, "cancel", broken)
    try:
        result = collect(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        assert "SECRET-CANCEL" not in json.dumps(result)
    finally:
        live.shutdown()


def test_durable_cancel_helper_rejects_bad_request_identifier(tmp_path: Path) -> None:
    from android_mcp_host.bugreport_control import cancel_bugreport

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        info = live.provisioner.verify_owned(NAME, handle)
        assert info is not None
        result = cancel_bugreport(
            jobs,
            OWNER,
            info,
            lid,
            "../foreign",
            "job_" + "x" * 32,
            lambda job_id: pytest.fail("Invalid request cannot signal cancellation"),
        )
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "INVALID_INPUT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()

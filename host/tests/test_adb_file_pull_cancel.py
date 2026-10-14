"""H4.d durable cooperative cancellation and bounded fake subprocess cleanup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from test_adb_file_pull_policy import (
    ART_OWNER,
    DIGEST,
    FILE,
    MIME,
    REMOTE,
    REQUEST,
    builder,
    pull,
)
from test_avd_provisioning import NAME, OWNER

from android_mcp_host.command_runner import bounded_run
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_file_pull import FilePullFrame


def cancel(
    worker: Any, handle: str, lid: str, jid: str, *, request_id: str = REQUEST
) -> dict[str, Any]:
    return worker.submit(
        "cancel",
        NAME,
        handle,
        lid,
        REMOTE,
        expected_sha256=DIGEST,
        mime_type=MIME,
        request_id=request_id,
        job_id=jid,
    )


def test_cancel_running_private_export_is_durable_and_prevents_publication(
    tmp_path: Path,
) -> None:
    started = threading.Event()
    observed_stop = threading.Event()
    result: dict[str, Any] = {}
    calls = [0]

    def slow(
        name: str,
        handle: str,
        lid: str,
        package: str,
        path: str,
        timeout: float,
        cap: int,
        stop: threading.Event,
    ) -> FilePullFrame:
        calls[0] += 1
        started.set()
        assert stop.wait(3), "Fake private export must be cancellable"
        observed_stop.set()
        return FilePullFrame(
            FILE, name, handle, lid, package, path, MIME, DIGEST, True, False, True
        )

    worker, live, jobs, store, handle, lid = builder(tmp_path, backend=slow)
    background = threading.Thread(
        target=lambda: result.update(pull(worker, handle, lid)),
        daemon=True,
    )
    try:
        background.start()
        assert started.wait(4)
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
        assert observed_stop.wait(4)
        background.join(timeout=4)
        assert not background.is_alive()
        assert calls == [1]
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "CANCELLED"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, jid)["job"]["state"] == "uncertain"
        replay = pull(worker, handle, lid)
        assert replay["status"] == "uncertain"
        assert replay["job_id"] == jid
        assert calls == [1]
        assert cancel(worker, handle, lid, jid)["status"] == "uncertain"
    finally:
        live.shutdown()


def test_cancel_wrong_job_and_credential_conflict_cannot_affect_completed_file(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    missing = "job_" + "x" * 32
    try:
        absent = cancel(worker, handle, lid, missing)
        assert absent["status"] == "blocked"
        assert absent["errors"][0]["code"] == "NOT_ACTIVE"
        complete = pull(worker, handle, lid)
        assert complete["status"] == "ok"
        terminal = cancel(worker, handle, lid, complete["job_id"])
        assert terminal["status"] == "blocked"
        assert terminal["errors"][0]["code"] == "NOT_ACTIVE"
        conflict = cancel(worker, handle, lid, complete["job_id"], request_id="different-request")
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert store.read(ART_OWNER, complete["artifact_handle"]) == FILE
        assert jobs.status(OWNER, complete["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


def test_cancel_invalid_identity_while_default_disabled(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path, consent=False)
    try:
        responses = (
            worker.submit(
                "cancel",
                NAME,
                handle,
                lid,
                REMOTE,
                request_id=REQUEST,
                expected_sha256=DIGEST,
                mime_type=MIME,
            ),
            worker.submit(
                "cancel",
                NAME,
                handle,
                lid,
                REMOTE,
                request_id=REQUEST,
                expected_sha256=DIGEST,
                mime_type=MIME,
                job_id="unsafe",
            ),
            worker.submit(
                "cancel",
                NAME,
                "USB-REAL",
                lid,
                REMOTE,
                request_id=REQUEST,
                expected_sha256=DIGEST,
                mime_type=MIME,
                job_id="job_" + "x" * 32,
            ),
        )
        assert all(resp["status"] == "blocked" for resp in responses)
        assert responses[0]["errors"][0]["code"] == "INVALID_INPUT"
        assert responses[-1]["errors"][0]["code"] == "NOT_OWNED"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_cancel_durable_store_failure_typed_without_leaking_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    first = pull(worker, handle, lid)

    def corrupt(*args: Any) -> Any:
        raise JobStoreError("PRIVATE-DATABASE-DENIED")

    monkeypatch.setattr(jobs, "lookup_request", corrupt)
    try:
        response = cancel(worker, handle, lid, first["job_id"])
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert "PRIVATE-DATABASE" not in json.dumps(response)
    finally:
        live.shutdown()


def test_synthetic_hung_transfer_has_bounded_process_group_timeout(
    tmp_path: Path,
) -> None:
    script = tmp_path / "fake-app-file-reader.py"
    marker = tmp_path / "synthetic-subprocess-id"
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(45)\n",
        encoding="utf-8",
    )
    worker, live, jobs, store, handle, lid = builder(tmp_path)

    def stuck(*args: Any) -> FilePullFrame:
        bounded_run([sys.executable, str(script), str(marker)], 0.6, 1024)
        pytest.fail("Hung fixture unexpectedly completed")

    worker._fixture = stuck
    try:
        reply = pull(worker, handle, lid)
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "TIMEOUT"
        assert marker.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, reply["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_stop_arriving_after_private_artifact_writes_revokes_both(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)
    put = store.put
    calls = [0]

    def inject_stop(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        calls[0] += 1
        row = put(owner, data, **kwargs)
        if calls[0] == 2:
            assert len(worker._active) == 1
            next(iter(worker._active.values())).set()
        return row

    monkeypatch.setattr(store, "put", inject_stop)
    try:
        output = pull(worker, handle, lid)
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "CANCELLED"
        assert calls == [2]
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, output["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_rollback_job_cancel_failure_does_not_echo_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)

    def timeout(*args: Any) -> FilePullFrame:
        raise subprocess.TimeoutExpired(["fake"], 0.01)

    worker._fixture = timeout

    def failed_cancel(*args: Any, **kwargs: Any) -> None:
        raise JobStoreError("PRIVATE-DB-TOKEN")

    monkeypatch.setattr(jobs, "cancel", failed_cancel)
    try:
        output = pull(worker, handle, lid)
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "TIMEOUT"
        assert "PRIVATE-DB-TOKEN" not in json.dumps(output)
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()

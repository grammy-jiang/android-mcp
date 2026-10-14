"""H4.f cancel and uncertain synthetic input execution, never real ADB."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from test_adb_emulator_ui_actions import (
    ART_OWNER,
    FOCUSED,
    GENERATION,
    REQUEST,
    ROTATION,
    WINDOW,
    builder,
    execute,
)
from test_avd_provisioning import NAME, OWNER

import android_mcp_host.synthetic_ui_actions as service
from android_mcp_host.command_runner import bounded_run
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_ui_actions import UiActionFrame


def cancel(
    worker: Any, handle: str, lid: str, job_id: str, *, request: str = REQUEST
) -> dict[str, Any]:
    return worker.submit(
        "cancel",
        "tap",
        NAME,
        handle,
        lid,
        WINDOW,
        GENERATION,
        ROTATION,
        FOCUSED,
        x=30,
        y=40,
        request_id=request,
        job_id=job_id,
    )


def test_t_h4f_05_cancels_only_active_action_and_signals_fixture(tmp_path: Path) -> None:
    active = threading.Event()
    stopped = threading.Event()
    output: dict[str, Any] = {}
    calls = [0]

    def runner(argv: list[str], stop: threading.Event) -> UiActionFrame:
        calls[0] += 1
        active.set()
        assert stop.wait(5), "Running synthetic input must respond to cancel"
        assert stop.is_set()
        stopped.set()
        return UiActionFrame(
            NAME,
            handle,
            lid,
            WINDOW,
            GENERATION,
            ROTATION,
            FOCUSED,
            True,
            True,
            True,
        )

    worker, live, jobs, artifacts, handle, lid, _ = builder(tmp_path, runner=runner)
    t = threading.Thread(
        target=lambda: output.update(execute(worker, handle, lid)),
        daemon=True,
    )
    try:
        t.start()
        assert active.wait(5)
        candidates = [
            item
            for item in jobs.list_status(OWNER)
            if item["job_id"] != lid and item["state"] == "running"
        ]
        assert len(candidates) == 1
        jid = candidates[0]["job_id"]
        halted = cancel(worker, handle, lid, jid)
        assert halted["status"] == "uncertain"
        assert halted["errors"][0]["code"] == "CANCELLED"
        assert stopped.wait(5)
        t.join(5)
        assert not t.is_alive()
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "CANCELLED"
        assert jobs.status(OWNER, jid)["job"]["state"] == "uncertain"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert calls == [1]
        assert execute(worker, handle, lid)["job_id"] == jid
        assert calls == [1]
        assert cancel(worker, handle, lid, jid)["status"] == "uncertain"
    finally:
        live.shutdown()


def test_cancel_wrong_job_and_changed_request_never_affect_prior_success(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        missing = cancel(worker, handle, lid, "job_" + "x" * 32)
        assert missing["status"] == "blocked"
        assert missing["errors"][0]["code"] == "NOT_ACTIVE"
        first = execute(worker, handle, lid)
        assert first["status"] == "simulated"
        terminal = cancel(worker, handle, lid, first["job_id"])
        assert terminal["status"] == "blocked"
        assert terminal["errors"][0]["code"] == "NOT_ACTIVE"
        different = cancel(worker, handle, lid, first["job_id"], request="other-request")
        assert different["status"] == "blocked"
        assert different["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert calls and len(calls) == 1
        assert jobs.status(OWNER, first["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


@pytest.mark.parametrize("job_id", [None, "bad", "job_" + "a" * 31, "job_" + "a" * 33])
def test_cancel_unvalidated_job_identifier_never_runs_fixture(
    tmp_path: Path,
    job_id: Any,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        output = worker.submit(
            "cancel",
            "tap",
            NAME,
            handle,
            lid,
            WINDOW,
            GENERATION,
            ROTATION,
            FOCUSED,
            x=30,
            y=40,
            request_id=REQUEST,
            job_id=job_id,
        )
        assert output["status"] == "blocked"
        assert output["errors"][0]["code"] == "INVALID_INPUT"
        assert calls == []
    finally:
        live.shutdown()


def test_cancel_after_private_report_created_revokes_uncommitted_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    original = artifacts.put

    def interrupt(owner: str, data: bytes, **kwargs: Any) -> dict[str, Any]:
        record = original(owner, data, **kwargs)
        assert len(worker._active) == 1
        next(iter(worker._active.values())).set()
        return record

    monkeypatch.setattr(artifacts, "put", interrupt)
    try:
        outcome = execute(worker, handle, lid)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "CANCELLED"
        assert outcome["report_handle"] is None
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_synthetic_hung_command_is_killed_with_no_orphan_process(tmp_path: Path) -> None:
    script = tmp_path / "fake-ui-input-hang.py"
    pidfile = tmp_path / "test-owned-pid"
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(45)\n",
        encoding="utf-8",
    )

    def stuck(argv: list[str], stop: threading.Event) -> UiActionFrame:
        bounded_run([sys.executable, str(script), str(pidfile)], 0.6, 1024)
        pytest.fail("Synthetic UI input unexpectedly completed")

    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path, runner=stuck)
    try:
        result = execute(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        assert pidfile.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_job_store_error_when_cancelling_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    first = execute(worker, handle, lid)

    def fault(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("PRIVATE-DB-CONFLICT")

    monkeypatch.setattr(jobs, "lookup_request", fault)
    try:
        blocked = cancel(worker, handle, lid, first["job_id"])
        assert blocked["status"] == "blocked"
        assert blocked["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert "PRIVATE" not in json.dumps(blocked)
    finally:
        live.shutdown()


def test_fixture_lock_denied_before_any_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(service, "claim_fixture_lock", lambda *args: None)
            assert execute(worker, handle, lid)["errors"][0]["code"] == "RECOVERY_REQUIRED"
        with monkeypatch.context() as patch:

            def fault(*args: Any) -> Any:
                raise OSError("PRIVATE-LOCK-ROOT")

            patch.setattr(service, "claim_fixture_lock", fault)
            assert execute(worker, handle, lid)["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert calls == []
    finally:
        live.shutdown()


def test_other_uncertain_job_blocks_unrelated_synthetic_UI_mutation(
    tmp_path: Path,
) -> None:
    import hashlib

    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    prior = jobs.prepare(
        OWNER,
        "unrelated-work",
        hashlib.sha256(b"unrelated").hexdigest(),
        identity=handle,
        authorized=True,
    )
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "RECOVERY_REQUIRED"
        assert prior["job_id"] not in worker._active
        assert calls == []
    finally:
        live.shutdown()


def test_disconnected_synthetic_emulator_cannot_accept_UI_input(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    live.shutdown()
    denied = execute(worker, handle, lid)
    assert denied["status"] == "blocked"
    assert denied["errors"][0]["code"] == "UNVERIFIED_TARGET"


def test_synthetic_emulator_disappearing_during_UI_mutation_is_uncertain(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    def loss(argv: list[str], stop: threading.Event) -> UiActionFrame:
        live.shutdown()
        return UiActionFrame(
            NAME, handle, lid, WINDOW, GENERATION, ROTATION, FOCUSED, True, True, True
        )

    worker._runner = loss
    result = execute(worker, handle, lid)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert artifacts.list_metadata(ART_OWNER) == []
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"

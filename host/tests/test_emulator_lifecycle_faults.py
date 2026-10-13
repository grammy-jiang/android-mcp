"""H3.c denial, journal transition and simulated worker failure regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST, engine

import android_mcp_host.emulator_lifecycle as lifecycle
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.synthetic_emulator_backend import SyntheticEmulatorError


def test_schema_must_be_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-emulator-lifecycle.v1.schema.json"
            return self

        def read_text(self, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(lifecycle, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        lifecycle.get_emulator_lifecycle_schema()


def test_invalid_action_and_unavailable_job_cannot_infer_process(tmp_path: Path) -> None:
    controller, handle, ledger, _ = engine(tmp_path, backend=False)
    assert controller.run("--bad-action", NAME, handle)["errors"][0]["code"] == "INVALID_ACTION"
    assert controller.run("status", NAME, handle)["errors"][0]["code"] == "INVALID_JOB"
    assert controller.run("stop", NAME, handle, job_id="job_" + "a" * 32)["status"] == "blocked"
    assert ledger.list_status(OWNER) == []
    assert controller.shutdown() == 0


def test_uncertain_durable_state_after_external_cancel_is_not_retried(tmp_path: Path) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    try:
        started = controller.run("start", NAME, handle, request_id=REQUEST)
        assert started["status"] == "ok"
        job_id = started["job_id"]
        ledger.cancel(OWNER, job_id, identity=handle, authorized=True)
        polled = controller.run("status", NAME, handle, job_id=job_id)
        assert polled["lifecycle_state"] == "uncertain"
        assert polled["process_confirmed"] is False
        assert controller.run("start", NAME, handle, request_id=REQUEST)["status"] == "uncertain"
    finally:
        controller.shutdown()


def test_unavailable_ledger_is_not_reported_as_a_running_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            ledger,
            "lookup_request",
            lambda *args: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
        )
        result = controller.run("start", NAME, handle, request_id=REQUEST)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "JOB_UNAVAILABLE"
    assert not ledger.list_status(OWNER)
    controller.shutdown()


def test_conflicting_plan_digest_is_blocked_without_launch(tmp_path: Path) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    different = ledger.prepare(
        OWNER,
        REQUEST,
        "a" * 64,
        identity=handle,
        authorized=True,
    )
    result = controller.run("start", NAME, handle, request_id=REQUEST)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    assert ledger.status(OWNER, different["job_id"])["job"]["attempts"] == 0
    controller.shutdown()


def test_unexpected_ledger_failure_before_dispatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            ledger,
            "prepare",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("RESOURCE_LIMIT")),
        )
        result = controller.run("start", NAME, handle, request_id=REQUEST)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "JOB_UNAVAILABLE"
    assert ledger.list_status(OWNER) == []
    controller.shutdown()


def test_runner_launch_failure_journal_is_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    with monkeypatch.context() as patch:
        patch.setattr(
            backend,
            "launch",
            lambda *args: (_ for _ in ()).throw(SyntheticEmulatorError("UNTRUSTED_FIXTURE")),
        )
        patch.setattr(
            ledger,
            "cancel",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
        )
        result = controller.run("start", NAME, handle, request_id=REQUEST)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "SPAWN_FAILED"
    assert len(ledger.list_status(OWNER)) == 1
    controller.shutdown()


def test_bad_readiness_and_failed_journal_finalization_never_claim_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path, emulator_kwargs={"boot": False})
    with monkeypatch.context() as patch:
        patch.setattr(
            ledger,
            "complete",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
        )
        result = controller.run("start", NAME, handle, request_id=REQUEST)
    assert result["status"] == "uncertain"
    assert result["process_confirmed"] is False
    controller.shutdown()


def test_failed_termination_and_cancel_failure_remain_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path, emulator_kwargs={"boot": False})
    assert backend is not None
    with monkeypatch.context() as patch:
        patch.setattr(backend, "stop", lambda child: False)
        patch.setattr(
            ledger,
            "cancel",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
        )
        result = controller.run("start", NAME, handle, request_id=REQUEST)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "READINESS_REJECTED"
    controller.shutdown()


def test_stop_not_confirmed_stays_uncertain_and_never_reclaims_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    try:
        started = controller.run("start", NAME, handle, request_id=REQUEST)
        assert started["status"] == "ok"
        with monkeypatch.context() as patch:
            patch.setattr(backend, "stop", lambda child: False)
            patch.setattr(
                ledger,
                "cancel",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
            )
            stopped = controller.run("stop", NAME, handle, job_id=started["job_id"])
            assert stopped["status"] == "uncertain"
            assert stopped["errors"][0]["code"] == "STOP_UNCONFIRMED"
    finally:
        controller.shutdown()


def test_completed_process_but_database_commit_fails_as_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    try:
        started = controller.run("start", NAME, handle, request_id=REQUEST)
        assert started["status"] == "ok"
        with monkeypatch.context() as patch:
            patch.setattr(
                ledger,
                "complete",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
            )
            result = controller.run("stop", NAME, handle, job_id=started["job_id"])
        assert result["status"] == "uncertain"
        assert result["process_confirmed"] is False
    finally:
        controller.shutdown()


def test_shutdown_job_storage_unavailable_does_not_signal_other_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    started = controller.run("start", NAME, handle, request_id=REQUEST)
    assert started["status"] == "ok"
    with monkeypatch.context() as patch:
        patch.setattr(
            ledger,
            "cancel",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
        )
        assert controller.shutdown() == 1
    assert controller.shutdown() == 0
    assert controller._sessions == {}


def test_status_without_session_never_resolves_running_from_ledger(tmp_path: Path) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    try:
        started = controller.run("start", NAME, handle, request_id=REQUEST)
        assert started["status"] == "ok"
        # The newly constructed controller lacks the session-owned Popen and
        # therefore cannot adopt any PID from a stale ledger record.
        other = lifecycle.EmulatorLifecycle(
            controller.provisioner, ledger, owner=OWNER, backend=backend
        )
        assert (
            other.run("status", NAME, handle, job_id=started["job_id"])["lifecycle_state"]
            == "uncertain"
        )
        assert other.shutdown() == 0
    finally:
        controller.shutdown()


def test_manual_job_ledger_record_with_wrong_identity_not_inferred(tmp_path: Path) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    try:
        info = controller.provisioner.verify_owned(NAME, handle)
        assert info is not None
        digest = controller._digest(info)
        stored = ledger.prepare(OWNER, "another-job", digest, identity=handle, authorized=True)
        wrong = "job_" + "z" * 32
        assert controller.run("status", NAME, handle, job_id=wrong)["status"] == "not_found"
        assert (
            controller.run("status", NAME, handle, job_id=stored["job_id"])["status"] == "uncertain"
        )
    finally:
        controller.shutdown()


def test_unexpected_synthetic_spawn_error_is_bounded_and_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    with monkeypatch.context() as patch:
        patch.setattr(
            backend,
            "launch",
            lambda *args: (_ for _ in ()).throw(OSError("PRIVATE FILESYSTEM SECRETS")),
        )
        result = controller.run("start", NAME, handle, request_id=REQUEST)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "SPAWN_FAILED"
    assert "PRIVATE" not in json.dumps(result)
    assert ledger.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    controller.shutdown()


def test_invalid_backend_report_is_never_trusted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    original = backend.launch
    with monkeypatch.context() as patch:
        patch.setattr(backend, "launch", lambda *args: (original(*args)[0], None))
        result = controller.run("start", NAME, handle, request_id=REQUEST)
    assert result["status"] in {"failed", "uncertain"}
    assert result["process_confirmed"] is False
    assert result["errors"][0]["code"] == "READINESS_REJECTED"
    controller.shutdown()


def test_status_storage_error_does_not_leak_private_job_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            ledger,
            "status",
            lambda *args: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
        )
        result = controller.run("status", NAME, handle, job_id="job_" + "x" * 32)
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "JOB_UNAVAILABLE"
    controller.shutdown()


def test_process_health_exception_for_running_fake_is_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    try:
        start = controller.run("start", NAME, handle, request_id=REQUEST)
        assert start["status"] == "ok"
        with monkeypatch.context() as patch:
            patch.setattr(
                backend,
                "is_running",
                lambda child: (_ for _ in ()).throw(OSError("private status")),
            )
            result = controller.run("status", NAME, handle, job_id=start["job_id"])
        assert result["status"] == "uncertain"
        assert result["process_confirmed"] is False
    finally:
        controller.shutdown()


def test_failed_fake_stop_exception_is_uncertain_not_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    try:
        start = controller.run("start", NAME, handle, request_id=REQUEST)
        assert start["status"] == "ok"
        with monkeypatch.context() as patch:
            patch.setattr(
                backend,
                "stop",
                lambda child: (_ for _ in ()).throw(OSError("private pid")),
            )
            result = controller.run("stop", NAME, handle, job_id=start["job_id"])
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "STOP_UNCONFIRMED"
    finally:
        controller.shutdown()


def test_shutdown_continues_when_fake_stop_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, handle, ledger, backend = engine(tmp_path)
    assert backend is not None
    original = backend.stop
    start = controller.run("start", NAME, handle, request_id=REQUEST)
    assert start["status"] == "ok"
    child = controller._sessions[start["job_id"]].process
    with monkeypatch.context() as patch:
        patch.setattr(
            backend,
            "stop",
            lambda one: (_ for _ in ()).throw(OSError("private failure")),
        )
        assert controller.shutdown() == 1
    assert original(child) is True
    assert controller.shutdown() == 0

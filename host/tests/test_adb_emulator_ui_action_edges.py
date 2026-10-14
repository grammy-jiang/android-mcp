"""H4.f bounded-window race, malformed schema and explicit denial branches."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_emulator_ui_actions import (
    ART_OWNER,
    FOCUSED,
    GENERATION,
    ROTATION,
    WINDOW,
    builder,
    execute,
)
from test_avd_provisioning import NAME, OWNER

from android_mcp_host.ui_action_support import (
    compile_safe_argv,
    coordinates_fit,
    valid_action_intent,
)


def test_invalid_kind_is_not_compiled_into_arbitrary_input() -> None:
    assert valid_action_intent("swipe-home") is False
    with pytest.raises(ValueError):
        compile_safe_argv(NAME, "command", x=30, y=40)
    with pytest.raises(ValueError):
        compile_safe_argv(NAME, "tap", x=30, y=40, keycode="KEYCODE_BACK")
    assert coordinates_fit("tap", True, 1080, 30, 40, None, None) is False


def test_bad_operation_types_fail_closed_with_no_fixture_effect(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        for operation in ("shell", "tap", ["execute"], {}, None):
            denied = worker.submit(
                operation,
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
                request_id="synthetic-ui-action-001",
            )
            assert denied["status"] == "blocked"
            assert denied["errors"][0]["code"] == "INVALID_ACTION"
        assert calls == []
    finally:
        live.shutdown()


def test_ui_schema_loader_rejects_non_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import synthetic_ui_actions as service

    class BadResource:
        def joinpath(self, name: str) -> BadResource:
            assert name == "host-synthetic-ui-actions.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(service, "files", lambda name: BadResource())
    with pytest.raises(ValueError):
        service.get_ui_action_schema()


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        (subprocess.TimeoutExpired(["fake-ui-witness"], 0.1), "TIMEOUT"),
        (OSError("PRIVATE-DATA"), "CAPABILITY_UNAVAILABLE"),
        (RuntimeError("PRIVATE-STATE"), "CAPABILITY_UNAVAILABLE"),
    ],
)
def test_unavailable_UI_witness_denies_before_any_action(
    tmp_path: Path,
    fault: Exception,
    expected: str,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    def bad_witness(*args: Any) -> Any:
        raise fault

    worker._witness = bad_witness
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == expected
        assert calls == []
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_missing_witness_helper_returns_explicit_unavailable(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    info = worker._provisioner.verify_owned(NAME, handle)
    assert info is not None
    worker._witness = None
    ctx = {
        "window_id": WINDOW,
        "generation": GENERATION,
        "rotation": ROTATION,
        "focused_node_id": FOCUSED,
        "kind": "tap",
    }
    try:
        assert (
            worker._check_witness(info, lid, ctx, (30, 40, None, None)) == "CAPABILITY_UNAVAILABLE"
        )
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
    finally:
        live.shutdown()


def test_per_intent_grant_expires_between_initial_check_and_job_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    approval = worker._approved
    invoked = [0]

    def expires(*args: Any) -> bool:
        invoked[0] += 1
        return approval(*args) if invoked[0] == 1 else False

    monkeypatch.setattr(worker, "_approved", expires)
    worker._runner = lambda *args: pytest.fail("Expired approval was ignored")
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert invoked == [2]
        assert jobs.status(OWNER, denied["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_focus_changed_after_action_cannot_publish_success_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    source = worker._witness
    assert source is not None
    called = [0]

    def window(*args: Any) -> Any:
        called[0] += 1
        old = source(*args)
        return replace(old, focused_node_id="node_changed") if called[0] == 2 else old

    monkeypatch.setattr(worker, "_witness", window)
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "STALE_WINDOW"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert called == [2]
    finally:
        live.shutdown()


def test_approval_expires_immediately_after_input_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    approved = worker._approved
    called = [0]

    def expire(*args: Any) -> bool:
        called[0] += 1
        return approved(*args) if called[0] < 3 else False

    monkeypatch.setattr(worker, "_approved", expire)
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert artifacts.list_metadata(ART_OWNER) == []
        assert called == [3]
    finally:
        live.shutdown()


def test_broken_grant_clock_cannot_authorize_synthetic_UI_input(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    worker._clock = lambda: (_ for _ in ()).throw(ValueError("PRIVATE-CLOCK"))
    worker._runner = lambda *args: pytest.fail("Invalid consent clock allowed input")
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()

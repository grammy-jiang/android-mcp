"""H4.f hostile intent, stale witness, grant and synthetic response tests."""

from __future__ import annotations

import subprocess
import time
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

from android_mcp_host.synthetic_ui_actions import (
    UiActionFrame,
    UiActionService,
)


@pytest.mark.parametrize(
    "change",
    [
        {"x": -1},
        {"x": 4096},
        {"x": True},
        {"x": "30"},
        {"y": -1},
        {"y": 4096},
        {"y": False},
        {"x2": 20},
        {"y2": 30},
        {"duration_ms": 150},
        {"keycode": "KEYCODE_HOME"},
        {"keycode": "KEYCODE_ENTER"},
    ],
)
def test_t_h4f_03_bad_tap_arguments_never_reach_synthetic_runner(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        denied = execute(worker, handle, lid, **change)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"x": -1},
        {"x": 4096},
        {"x": 3.4},
        {"y": -1},
        {"x2": -1},
        {"y2": 4096},
        {"x2": "1; touch /tmp/private"},
        {"duration_ms": 0},
        {"duration_ms": 99},
        {"duration_ms": 2001},
        {"duration_ms": True},
        {"keycode": "KEYCODE_BACK"},
    ],
)
def test_t_h4f_03_bad_swipe_arguments_denied_without_input(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path, kind="swipe")
    try:
        denied = execute(worker, handle, lid, kind="swipe", **change)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"keycode": "--text=secret"},
        {"keycode": "KEYCODE_ENTER"},
        {"keycode": "KEYCODE_POWER"},
        {"keycode": None},
        {"x": 0},
        {"y": 0},
        {"duration_ms": 200},
    ],
)
def test_t_h4f_03_unsupported_keycode_or_text_input_denied(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path, kind="key")
    try:
        denied = execute(worker, handle, lid, kind="key", **change)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"window_generation": 0},
        {"window_generation": -1},
        {"window_generation": True},
        {"window_generation": 2147483648},
        {"window_id": "../other"},
        {"window_id": "emulator-5554"},
        {"window_id": "win_\nattack"},
        {"rotation": -1},
        {"rotation": 4},
        {"rotation": "0"},
        {"rotation": True},
        {"focused_node_id": "../focus"},
        {"focused_node_id": "node_🚀"},
    ],
)
def test_t_h4f_03_malformed_window_generation_focus_and_rotation_denied(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    params: dict[str, Any] = {
        "operation": "execute",
        "kind": "tap",
        "avd_name": NAME,
        "avd_handle": handle,
        "lifecycle_job_id": lid,
        "window_id": WINDOW,
        "window_generation": GENERATION,
        "rotation": ROTATION,
        "focused_node_id": FOCUSED,
        "x": 30,
        "y": 40,
        "request_id": "synthetic-ui-action-001",
    }
    params.update(change)
    try:
        denied = worker.submit(**params)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "grant_change",
    [
        {"owner": "foreign"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"window_id": "win_wrong"},
        {"window_generation": GENERATION + 1},
        {"rotation": 2},
        {"focused_node_id": "node_another"},
        {"intent_sha256": "0" * 64},
        {"purpose": "other-purpose"},
        {"valid_until_epoch": 0},
        {"valid_until_epoch": time.time() + 600},
        {"valid_until_epoch": float("nan")},
        {"valid_until_epoch": float("inf")},
        {"valid_until_epoch": True},
        {"valid_until_epoch": "bad-clock"},
        {"ttl_s": 0},
        {"ttl_s": 301},
        {"ttl_s": float("nan")},
        {"ttl_s": float("inf")},
        {"ttl_s": "bad"},
        {"ttl_s": True},
    ],
)
def test_t_h4f_02_missing_or_invalid_per_intent_approval_never_runs(
    tmp_path: Path,
    grant_change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    assert worker._approval is not None
    worker._approval = replace(worker._approval, **grant_change)
    worker._runner = lambda *args: pytest.fail("Untrusted UI action executed")
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
        assert len(jobs.list_status(OWNER)) == 1
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"avd_handle": "mcpavd_" + "x" * 32}, "STALE_WINDOW"),
        ({"lifecycle_job_id": "job_" + "x" * 32}, "STALE_WINDOW"),
        ({"window_id": "win_wrong"}, "STALE_WINDOW"),
        ({"window_generation": GENERATION + 1}, "STALE_WINDOW"),
        ({"rotation": 2}, "STALE_WINDOW"),
        ({"focused_node_id": "node_wrong"}, "STALE_WINDOW"),
        ({"synthetic": False}, "STALE_WINDOW"),
        ({"secure_window": "false"}, "STALE_WINDOW"),
        ({"locked_window": None}, "STALE_WINDOW"),
        ({"width": 0}, "STALE_WINDOW"),
        ({"height": 4097}, "STALE_WINDOW"),
        ({"secure_window": True}, "WINDOW_PROTECTED"),
        ({"locked_window": True}, "WINDOW_PROTECTED"),
    ],
)
def test_t_h4f_04_spoofed_protected_or_stale_witness_blocked(
    tmp_path: Path,
    change: dict[str, Any],
    expected: str,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    original = worker._witness
    assert original is not None
    worker._witness = lambda *args: replace(original(*args), **change)
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == expected
        assert calls == []
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"avd_name": "other"},
        {"avd_handle": "mcpavd_" + "x" * 32},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"window_id": "win_wrong"},
        {"window_generation": GENERATION + 1},
        {"rotation": 2},
        {"focused_node_id": "node_changed"},
        {"complete": 1},
        {"applied": "true"},
        {"synthetic": False},
    ],
)
def test_t_h4f_04_invalid_runner_metadata_cannot_be_accepted(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    def tampered(*args: Any) -> UiActionFrame:
        return replace(
            UiActionFrame(
                NAME, handle, lid, WINDOW, GENERATION, ROTATION, FOCUSED, True, True, True
            ),
            **change,
        )

    worker._runner = tampered
    try:
        outcome = execute(worker, handle, lid)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "BAD_FRAME"
        assert outcome["report_handle"] is None
        assert artifacts.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "change",
    [{"complete": False}, {"applied": False}],
)
def test_t_h4f_05_partial_or_unconfirmed_fixture_input_never_claims_success(
    tmp_path: Path,
    change: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    worker._runner = lambda *args: replace(
        UiActionFrame(NAME, handle, lid, WINDOW, GENERATION, ROTATION, FOCUSED, True, True, True),
        **change,
    )
    try:
        result = execute(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "PARTIAL_ACTION"
        assert result["report_handle"] is None
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("problem", "reason"),
    [
        (subprocess.TimeoutExpired(["fake-ui"], 0.01), "TIMEOUT"),
        (OSError("PRIVATE-PATH"), "RUNNER_FAILED"),
        (RuntimeError("PRIVATE-STATE"), "RUNNER_FAILED"),
        (subprocess.CalledProcessError(1, ["fake-ui"]), "RUNNER_FAILED"),
    ],
)
def test_t_h4f_05_synthetic_runner_errors_do_not_disclose_secrets(
    tmp_path: Path,
    problem: Exception,
    reason: str,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any) -> UiActionFrame:
        raise problem

    worker._runner = fail
    try:
        outcome = execute(worker, handle, lid)
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == reason
        assert "PRIVATE-" not in str(outcome)
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "uncertain"
        assert artifacts.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_ui_action_constructor_rejects_owner_mismatch(tmp_path: Path) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        for owner, art_owner in (("foreign", ART_OWNER), (OWNER, "bad/path")):
            with pytest.raises(ValueError):
                UiActionService(
                    live.provisioner,
                    live,
                    jobs,
                    artifacts,
                    owner=owner,
                    artifact_owner=art_owner,
                )
    finally:
        live.shutdown()

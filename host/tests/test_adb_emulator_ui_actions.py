"""H4.f six required synthetic UI action acceptance scenarios.

No ADB input binary, physical tablet, Accessibility grant or OS UI state is
accessed by these fixtures.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as START_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

WINDOW = "win_fixture_001"
GENERATION = 7
ROTATION = 0
FOCUSED = "node_button"
ART_OWNER = "private-ui-action-audit"
REQUEST = "synthetic-ui-action-001"
SIZE = (1080, 1920)


def intent(kind: str = "tap") -> dict[str, Any]:
    if kind == "tap":
        return {"kind": "tap", "x": 30, "y": 40}
    if kind == "swipe":
        return {"kind": "swipe", "x": 30, "y": 40, "x2": 80, "y2": 120, "duration_ms": 500}
    assert kind == "key"
    return {"kind": "key", "keycode": "KEYCODE_BACK"}


def builder(
    tmp_path: Path,
    *,
    kind: str = "tap",
    active: bool = True,
    approved: bool = True,
    runner: Any = None,
    witness: Any = None,
) -> tuple[Any, Any, Any, PrivateArtifactStore, str, str, list[list[str]]]:
    from android_mcp_host.synthetic_ui_actions import (
        UiActionApproval,
        UiActionFrame,
        UiActionService,
        UiWitness,
    )
    from android_mcp_host.ui_action_support import intent_digest

    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        started = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert started["status"] == "ok"
        lid = started["job_id"]
    artifacts = PrivateArtifactStore(tmp_path / "private-ui-action-audit")
    frame = UiWitness(
        handle,
        lid,
        WINDOW,
        GENERATION,
        ROTATION,
        FOCUSED,
        SIZE[0],
        SIZE[1],
        False,
        False,
        True,
    )
    if witness is None:

        def fake_witness(
            name: str, avd_handle: str, lifecycle_id: str, seconds: float
        ) -> UiWitness:
            return frame

        witness = fake_witness
    approval = (
        UiActionApproval(
            OWNER,
            handle,
            lid,
            WINDOW,
            GENERATION,
            ROTATION,
            FOCUSED,
            intent_digest(**intent(kind)),
            "synthetic-ui-input",
            time.time() + 120,
            120,
        )
        if approved
        else None
    )
    calls: list[list[str]] = []
    if runner is None:

        def runner(argv: list[str], stop: threading.Event) -> UiActionFrame:
            calls.append(argv)
            assert not stop.is_set()
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

    worker = UiActionService(
        live.provisioner,
        live,
        jobs,
        artifacts,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        approval=approval,
        fixture_witness=witness,
        fixture_runner=runner,
    )
    return worker, live, jobs, artifacts, handle, lid, calls


def execute(
    worker: Any,
    handle: str,
    lid: str,
    *,
    kind: str = "tap",
    request: str = REQUEST,
    operation: str = "execute",
    **overrides: Any,
) -> dict[str, Any]:
    args = dict(intent(kind))
    args.update(overrides)
    target = {
        "operation": operation,
        "avd_name": NAME,
        "avd_handle": handle,
        "lifecycle_job_id": lid,
        "window_id": WINDOW,
        "window_generation": GENERATION,
        "rotation": ROTATION,
        "focused_node_id": FOCUSED,
        "request_id": request,
    }
    return worker.submit(**target, **args)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("tap", ["fixture-ui-input", "--avd", NAME, "tap", "30", "40"]),
        (
            "swipe",
            [
                "fixture-ui-input",
                "--avd",
                NAME,
                "swipe",
                "30",
                "40",
                "80",
                "120",
                "500",
            ],
        ),
        ("key", ["fixture-ui-input", "--avd", NAME, "key", "KEYCODE_BACK"]),
    ],
)
def test_t_h4f_01_verified_exact_synthetic_ui_intent_uses_only_fixed_argv(
    tmp_path: Path,
    kind: str,
    expected: list[str],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path, kind=kind)
    try:
        outcome = execute(worker, handle, lid, kind=kind)
        assert outcome["status"] == "simulated"
        assert outcome["action_state"] == "applied_synthetic"
        assert outcome["job_id"].startswith("job_")
        assert outcome["report_handle"].startswith("art_")
        assert outcome["window_generation"] == GENERATION
        assert outcome["focused_node_id"] == FOCUSED
        assert outcome["real_ui_input_enabled"] is False
        assert outcome["physical_device_writes_enabled"] is False
        assert outcome["synthetic_fixture_only"] is True
        assert calls == [expected]
        assert not any(token in expected for token in ("shell", "-c", "bash", "sh"))
        assert jobs.status(OWNER, outcome["job_id"])["job"]["state"] == "succeeded"
        assert artifacts.public_metadata(ART_OWNER, outcome["report_handle"])["status"] == "ok"
        assert str(tmp_path) not in json.dumps(outcome)
    finally:
        live.shutdown()


def test_t_h4f_02_missing_grant_or_foreign_physical_device_denied(tmp_path: Path) -> None:
    calls: list[bool] = []

    def forbidden(*args: Any) -> Any:
        calls.append(True)
        pytest.fail("Unknown target triggered fake input")

    worker, live, jobs, artifacts, handle, lid, _ = builder(
        tmp_path,
        approved=False,
        runner=forbidden,
    )
    try:
        denied = execute(worker, handle, lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
        assert execute(worker, "USB-physical", lid)["status"] == "blocked"
        assert (
            worker.submit(
                "execute",
                "tap",
                "emulator-5554",
                handle,
                lid,
                WINDOW,
                GENERATION,
                ROTATION,
                FOCUSED,
                x=30,
                y=40,
                request_id=REQUEST,
            )["status"]
            == "blocked"
        )
        assert calls == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "bad",
    [
        {"x": -1},
        {"x": 5000},
        {"x": "1; rm -rf /"},
        {"y": -10},
        {"y": 2001},
        {"x": True},
        {"y": 1.0},
        {"keycode": "KEYCODE_ENTER"},
        {"keycode": "--shell"},
        {"duration_ms": 0},
        {"duration_ms": 9000},
        {"x2": "../escape"},
        {"x2": -1},
    ],
)
def test_t_h4f_03_bad_coordinates_duration_keycodes_or_flags_blocked(
    tmp_path: Path,
    bad: dict[str, Any],
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        invalid = execute(worker, handle, lid, **bad)
        assert invalid["status"] == "blocked"
        assert invalid["errors"][0]["code"] == "INVALID_INPUT"
        assert calls == []
    finally:
        live.shutdown()


def test_t_h4f_04_stale_generation_rotation_focus_cannot_target_a_window(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    observed = [0]
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    original = worker._witness
    assert original is not None
    changes = [
        {"window_generation": GENERATION + 1},
        {"rotation": 1},
        {"focused_node_id": "node_foreign"},
        {"window_id": "win_another_001"},
    ]
    try:
        for change in changes:
            worker._witness = lambda *args, change=change: replace(original(*args), **change)
            denied = execute(worker, handle, lid)
            assert denied["status"] == "blocked"
            assert denied["errors"][0]["code"] == "STALE_WINDOW"
            observed[0] += 1
        assert observed == [4]
        assert calls == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h4f_05_replay_uses_same_job_and_never_reissues_input(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)
    try:
        first = execute(worker, handle, lid)
        assert first["status"] == "simulated"
        assert execute(worker, handle, lid) == first
        assert len(calls) == 1
        conflict = execute(worker, handle, lid, request="different-request")
        assert conflict["status"] == "blocked"
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(calls) == 1
        assert len(jobs.list_status(OWNER)) == 2
    finally:
        live.shutdown()


def test_t_h4f_06_fastmcp_typed_sensitive_tool_no_generic_shell(
    tmp_path: Path,
) -> None:
    from android_mcp_host.synthetic_ui_actions import get_ui_action_schema

    worker, live, jobs, artifacts, handle, lid, calls = builder(
        tmp_path, active=False, approved=False
    )

    async def check() -> None:
        async with Client(create_server()) as original:
            baseline = {item.name: item for item in await original.list_tools()}
        async with Client(create_server(ui_action_worker=worker)) as client:
            tools = {item.name: item for item in await client.list_tools()}
            assert set(tools) == {*baseline, "host_ui_action"}
            assert all(tools[k] == baseline[k] for k in baseline)
            tool = tools["host_ui_action"]
            assert tool.output_schema == get_ui_action_schema()
            Draft202012Validator.check_schema(tool.output_schema)
            annotations = tool.annotations.model_dump(mode="json", by_alias=True)
            assert annotations["destructiveHint"] is True
            assert annotations["readOnlyHint"] is False
            assert annotations["openWorldHint"] is False
            kwargs = {
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
            }
            planned = await client.call_tool("host_ui_action", {"operation": "plan", **kwargs})
            assert planned.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_ui_action", {"operation": "execute", "request_id": REQUEST, **kwargs}
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["errors"][0]["code"] == "MUTATION_DISABLED"
            assert denied.structured_content["real_ui_input_enabled"] is False
            Draft202012Validator(get_ui_action_schema()).validate(denied.structured_content)

    try:
        asyncio.run(check())
    finally:
        live.shutdown()

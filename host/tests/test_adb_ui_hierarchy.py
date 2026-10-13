"""H4.b mandatory private, redacted UI hierarchy contract tests.

All capabilities are synthetic fixtures only; no Android Accessibility,
real uiautomator, physical USB/ADB target or generic input is accessed.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as START_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.server import create_server

REQUEST = "ui-inspection-001"
WIN = "win_synthetic_001"


def ui_fixture(*, secret: bool = True) -> bytes:
    """Tiny self-contained UIAutomator-shaped synthetic hierarchy."""
    password = (
        (
            '<node node-id="node_password" class="android.widget.EditText" '
            'resource-id="org.example:id/password" text="a-very-private-password" '
            'content-desc="PIN 1234" password="true" focused="false" />'
        )
        if secret
        else ""
    )
    return (
        '<hierarchy rotation="0">'
        '<node node-id="node_root" class="android.widget.FrameLayout" '
        'resource-id="org.example:id/root" text="" content-desc="" '
        'password="false" focused="false">'
        '<node node-id="node_title" class="android.widget.TextView" '
        'resource-id="org.example:id/title" text="Hello world" '
        'content-desc="Welcome" password="false" focused="true"/>'
        + password
        + '<node node-id="node_notice" class="android.widget.TextView" '
        'resource-id="org.example:id/notification_message" '
        'text="Private SMS code 4812" content-desc="notification content" '
        'password="false" focused="false"/>'
        '<node node-id="node_token" class="android.widget.TextView" '
        'resource-id="org.example:id/status" text="Bearer secret-abc-123" '
        'content-desc="access_token = confidential" '
        'password="false" focused="false"/>'
        "</node></hierarchy>"
    ).encode("utf-8")


def builder(
    tmp_path: Path,
    *,
    active: bool = True,
    consent: bool = True,
    fixture_reader: Any = None,
) -> tuple[Any, Any, Any, str, str]:
    from android_mcp_host.synthetic_ui_hierarchy import (
        UiApproval,
        UiHierarchyService,
        UiTreeFrame,
    )

    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        started = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert started["status"] == "ok"
        lid = started["job_id"]

    approval = (
        UiApproval(OWNER, handle, lid, "synthetic-ui-inspection", time.time() + 120)
        if consent
        else None
    )
    if fixture_reader is None:

        def fixture_reader(
            name: str, handle: str, lid: str, seconds: float, limit: int
        ) -> UiTreeFrame:
            assert seconds <= 5 and limit <= 32768
            return UiTreeFrame(
                ui_fixture(),
                name,
                handle,
                lid,
                WIN,
                False,
                False,
                True,
                True,
                "normal",
                "normal",
            )

    worker = UiHierarchyService(
        live.provisioner,
        live,
        jobs,
        owner=OWNER,
        approval=approval,
        fixture_reader=fixture_reader,
    )
    return worker, live, jobs, handle, lid


def inspect(worker: Any, handle: str, lid: str, *, request: str = REQUEST) -> dict[str, Any]:
    return worker.submit("inspect", NAME, handle, lid, request_id=request)


def test_t_h4b_01_verified_synthetic_ui_nodes_and_focus(tmp_path: Path) -> None:
    calls: list[Any] = []

    def fake(*args: Any) -> Any:
        calls.append(args)
        from android_mcp_host.synthetic_ui_hierarchy import UiTreeFrame

        name, handle, lid, _, _ = args
        return UiTreeFrame(
            ui_fixture(), name, handle, lid, WIN, False, False, True, True, "normal", "normal"
        )

    worker, live, jobs, handle, lid = builder(tmp_path, fixture_reader=fake)
    try:
        result = inspect(worker, handle, lid)
        assert result["status"] == "ok"
        assert result["window_id"] == WIN
        assert result["node_count"] == 5
        assert result["focused_node_id"] == "node_title"
        assert result["rotation"] == 0
        assert result["nodes"][0]["id"] == "node_root"
        assert result["nodes"][0]["parent_id"] is None
        assert result["nodes"][1]["parent_id"] == "node_root"
        assert result["nodes"][1]["text"] == "Hello world"
        assert result["synthetic_fixture_only"] is True
        assert result["real_ui_access_enabled"] is False
        assert result["physical_device_writes_enabled"] is False
        assert result["sensitivity_class"] == "redacted_ui"
        assert len(calls) == 1
        assert calls[0][:3] == (NAME, handle, lid)
        assert calls[0][3:] == (3.0, 32768)
        assert str(tmp_path) not in json.dumps(result)
        assert [job["job_id"] for job in jobs.list_status(OWNER)] == [lid]
    finally:
        live.shutdown()


def test_t_h4b_02_absent_permission_foreign_or_locked_target_denied(tmp_path: Path) -> None:
    calls: list[str] = []

    def must_not_read(*args: Any) -> Any:
        calls.append("invoked")
        raise AssertionError("Unauthorized UI capture")

    worker, live, jobs, handle, lid = builder(tmp_path, consent=False, fixture_reader=must_not_read)
    try:
        assert inspect(worker, handle, lid)["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert (
            worker.submit("inspect", "emulator-5554", handle, lid, request_id=REQUEST)["status"]
            == "blocked"
        )
        assert inspect(worker, "mcpavd_" + "x" * 32, lid)["status"] == "blocked"
        assert inspect(worker, handle, "job_" + "x" * 32)["status"] == "blocked"
        assert calls == []
        assert [job["job_id"] for job in jobs.list_status(OWNER)] == [lid]
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "xml",
    [
        b"",
        b"<hierarchy rotation='0'><node",
        b"<!DOCTYPE hierarchy [<!ENTITY e SYSTEM 'file:///etc/passwd'>]>"
        b"<hierarchy rotation='0'>&e;</hierarchy>",
        b"<hierarchy rotation='0'><node node-id='node_a' class='android.widget.TextView' "
        b"focused='false' password='false' /><node node-id='node_a' "
        b"class='android.widget.Button' focused='false' password='false'/></hierarchy>",
        b"<hierarchy rotation='0' />",
        b"<hierarchy rotation='0'><junk /></hierarchy>",
        b"<hierarchy rotation='0'><node node-id='node_a' class='Button' "
        b"focused='false' password='false'><node node-id='node_b' "
        b"class='Button' focused='true' password='false'/><node node-id='node_c' "
        b"class='Button' focused='true' password='false'/></node></hierarchy>",
        b"<hierarchy rotation='0'><node node-id='node_a' class='Button' "
        b"focused='false' password='false' text='\xff'/></hierarchy>",
    ],
)
def test_t_h4b_03_invalid_or_malicious_xml_rejected(xml: bytes) -> None:
    from android_mcp_host.ui_hierarchy_support import InvalidUiTree, parse_ui_xml

    with pytest.raises(InvalidUiTree):
        parse_ui_xml(xml)


def test_t_h4b_04_password_notifications_and_tokens_redacted(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)
    try:
        result = inspect(worker, handle, lid)
        assert result["status"] == "ok"
        nodes = {node["id"]: node for node in result["nodes"]}
        assert nodes["node_title"]["text"] == "Hello world"
        assert nodes["node_password"]["text"] == "[REDACTED]"
        assert nodes["node_password"]["content_description"] == "[REDACTED]"
        assert nodes["node_notice"]["text"] == "[REDACTED]"
        assert nodes["node_token"]["text"] == "[REDACTED]"
        assert nodes["node_token"]["content_description"] == "[REDACTED]"
        data = json.dumps(result)
        for forbidden in (
            "password" + "a-very-private",
            "4812",
            "confidential",
            "secret-abc-123",
            "Private SMS",
        ):
            assert forbidden not in data
    finally:
        live.shutdown()


def test_t_h4b_05_bounded_timeout_connection_failure_and_mode_change(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_ui_hierarchy import UiTreeFrame

    def timeout(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fixture-uiautomator"], 0.02)

    worker, live, jobs, handle, lid = builder(tmp_path, fixture_reader=timeout)
    try:
        result = inspect(worker, handle, lid)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        worker._fixture = lambda name, handle, lid, seconds, limit: UiTreeFrame(
            ui_fixture(),
            name,
            handle,
            lid,
            WIN,
            False,
            False,
            True,
            True,
            "normal",
            "locked",
        )
        assert inspect(worker, handle, lid)["errors"][0]["code"] == "MODE_CHANGED"
        worker._fixture = lambda *args: (_ for _ in ()).throw(OSError("PRIVATE-CREDENTIAL"))
        failed = inspect(worker, handle, lid)
        assert failed["status"] == "unavailable"
        assert "PRIVATE-CREDENTIAL" not in json.dumps(failed)
    finally:
        live.shutdown()


def test_t_h4b_06_fastmcp_schema_and_legacy_tools_unchanged(tmp_path: Path) -> None:
    from android_mcp_host.synthetic_ui_hierarchy import get_ui_hierarchy_schema

    worker, live, _, handle, lid = builder(tmp_path, active=False, consent=False)

    async def verify() -> None:
        async with Client(create_server()) as base:
            existing = {t.name: t for t in await base.list_tools()}
        async with Client(create_server(ui_hierarchy_worker=worker)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*existing, "host_ui_hierarchy"}
            assert all(tools[name] == existing[name] for name in existing)
            schema = get_ui_hierarchy_schema()
            Draft202012Validator.check_schema(schema)
            assert tools["host_ui_hierarchy"].output_schema == schema
            hints = tools["host_ui_hierarchy"].annotations.model_dump(mode="json", by_alias=True)
            assert hints["destructiveHint"] is True
            assert hints["readOnlyHint"] is False
            planned = await client.call_tool(
                "host_ui_hierarchy",
                {"action": "plan", "avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid},
            )
            assert planned.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_ui_hierarchy",
                {
                    "action": "inspect",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "request_id": REQUEST,
                },
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["nodes"] == []
            Draft202012Validator(schema).validate(denied.structured_content)

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()

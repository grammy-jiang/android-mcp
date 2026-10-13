"""H4.b production plan-only CLI and genuine localhost Streamable HTTP MCP."""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_adb_ui_hierarchy import REQUEST, WIN, builder, ui_fixture
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.synthetic_ui_hierarchy import (
    UiHierarchyService,
    get_ui_hierarchy_schema,
)


def test_opt_in_cli_never_exposes_real_android_ui_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def server(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", server)
        for invalid in (
            ["serve", "--ui-hierarchy-plan"],
            ["serve", "--ui-hierarchy-plan", "--avd-provision"],
            ["serve", "--ui-hierarchy-plan", "--durable-job-status"],
        ):
            with pytest.raises(SystemExit) as failure:
                cli.main(invalid)
            assert failure.value.code == 2
        assert calls == []
        assert cli.main([*make_flags(tmp_path), "--ui-hierarchy-plan"]) == 0
        assert len(calls) == 1
        worker = calls[0]["ui_hierarchy_worker"]
        assert isinstance(worker, UiHierarchyService)
        assert worker._owner == OWNER
        assert worker._approval is None
        assert worker._fixture is None


def test_ui_tree_plan_cli_cross_owner_rejected_before_any_local_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = [*make_flags(tmp_path), "--ui-hierarchy-plan"]
    args[args.index("--job-owner") + 1] = "wrong-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as denied:
            cli.main(args)
    assert denied.value.code == 2
    assert not (tmp_path / "owned-avds").exists()
    assert not (tmp_path / "jobs").exists()


def test_in_process_mcp_returns_only_redacted_nodes(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid = builder(tmp_path)

    async def verify() -> None:
        async with Client(cli.create_server(ui_hierarchy_worker=worker)) as client:
            result = await client.call_tool(
                "host_ui_hierarchy",
                {
                    "action": "inspect",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "request_id": REQUEST,
                },
            )
            assert not result.is_error
            data = result.structured_content
            Draft202012Validator(get_ui_hierarchy_schema()).validate(data)
            assert data["status"] == "ok"
            assert data["window_id"] == WIN
            assert data["focused_node_id"] == "node_title"
            assert data["node_count"] == 5
            assert data["nodes"][1]["text"] == "Hello world"
            serialized = json.dumps(data)
            assert "Private SMS" not in serialized
            assert "a-very-private-password" not in serialized
            assert "secret-abc-123" not in serialized
            assert ui_fixture().decode("utf-8") not in serialized

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()


def test_actual_localhost_mcp_ui_tree_has_no_live_executable_or_permission(
    tmp_path: Path,
) -> None:
    target = provider(tmp_path)
    created = target.provision("create", NAME)
    assert created["status"] == "created"
    handle = created["avd"]["handle"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    source = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.synthetic_ui_hierarchy import UiHierarchyService\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobs_root=Path(sys.argv[3])\n"
        "owner=sys.argv[4]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[5],"
        "system_image_sha256=sys.argv[6],license_sha256=sys.argv[7])\n"
        "jobs=DurableJobStore(jobs_root)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "worker=UiHierarchyService(avd,live,jobs,owner=owner)\n"
        "create_server(ui_hierarchy_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[8]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            source,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            str(tmp_path / "jobs"),
            OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def check() -> None:
        latest: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_ui_hierarchy",
                    }
                    tool = tools["host_ui_hierarchy"]
                    assert tool.output_schema == get_ui_hierarchy_schema()
                    hints = tool.annotations.model_dump(mode="json", by_alias=True)
                    assert hints["destructiveHint"] is True
                    assert hints["readOnlyHint"] is False
                    assert "raw XML" in tool.description
                    request = {
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                    }
                    plan = await client.call_tool(
                        "host_ui_hierarchy", {"action": "plan", **request}
                    )
                    assert plan.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_ui_hierarchy",
                        {"action": "inspect", **request, "request_id": REQUEST},
                    )
                    data = denied.structured_content
                    assert not denied.is_error
                    Draft202012Validator(get_ui_hierarchy_schema()).validate(data)
                    assert data["status"] == "blocked"
                    assert data["nodes"] == []
                    assert data["errors"][0]["code"] == "CONSENT_REQUIRED"
                    serialized = json.dumps(data)
                    assert str(tmp_path) not in serialized
                    assert OWNER not in serialized
                    assert data["real_ui_access_enabled"] is False
                    assert data["accessibility_bypass_enabled"] is False
                    return
            except Exception as error:
                latest = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic hierarchy local MCP unavailable: {latest!r}")

    try:
        asyncio.run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    assert process.poll() is not None

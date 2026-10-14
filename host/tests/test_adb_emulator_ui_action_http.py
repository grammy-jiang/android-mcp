"""H4.f production opt-in and actual localhost Streamable HTTP MCP contract."""

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
from test_adb_emulator_ui_actions import (
    ART_OWNER,
    FOCUSED,
    GENERATION,
    REQUEST,
    ROTATION,
    WINDOW,
    builder,
)
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.synthetic_ui_actions import UiActionService, get_ui_action_schema


def flags(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "private-ui-audit"),
        "--artifact-owner",
        ART_OWNER,
        "--ui-action-plan",
    ]


def test_default_cli_only_offers_scoped_plans_and_no_action_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kw: Any) -> None:
            assert kw == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **kw: calls.append(kw) or Stub())
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for invalid in (
            ["serve", "--ui-action-plan"],
            ["serve", "--ui-action-plan", "--avd-provision"],
            ["serve", "--ui-action-plan", "--artifact-metadata"],
            ["serve", "--ui-action-plan", "--durable-job-status"],
        ):
            with pytest.raises(SystemExit) as error:
                cli.main(invalid)
            assert error.value.code == 2
            assert calls == []
        assert cli.main(flags(tmp_path)) == 0
        assert len(calls) == 1
        worker = calls[0]["ui_action_worker"]
        assert isinstance(worker, UiActionService)
        assert worker._owner == OWNER
        assert worker._artifact_owner == ART_OWNER
        assert worker._approval is None
        assert worker._runner is None
        assert worker._witness is None
    assert not (tmp_path / "owned-avds").exists()


def test_ui_action_cli_cross_owner_denied_before_private_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = flags(tmp_path)
    command[command.index("--job-owner") + 1] = "other-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as error:
            cli.main(command)
    assert error.value.code == 2
    assert not (tmp_path / "private-ui-audit").exists()
    assert not (tmp_path / "owned-avds").exists()


def test_inprocess_fastmcp_returns_only_synthetic_UI_action_private_receipt(
    tmp_path: Path,
) -> None:
    worker, live, jobs, artifacts, handle, lid, calls = builder(tmp_path)

    async def inspect() -> None:
        async with Client(cli.create_server(ui_action_worker=worker)) as client:
            result = await client.call_tool(
                "host_ui_action",
                {
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
                    "request_id": REQUEST,
                },
            )
            assert not result.is_error
            receipt = result.structured_content
            Draft202012Validator(get_ui_action_schema()).validate(receipt)
            assert receipt["status"] == "simulated"
            assert receipt["action_id"] == receipt["job_id"]
            assert receipt["report_handle"].startswith("art_")
            assert receipt["real_ui_input_enabled"] is False
            assert receipt["generic_shell_enabled"] is False
            assert receipt["preview_argv"] == []
            assert str(tmp_path) not in json.dumps(receipt)

    try:
        asyncio.run(inspect())
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_localhost_http_UI_action_catalog_and_denial_contract(
    tmp_path: Path,
) -> None:
    prov = provider(tmp_path)
    created = prov.provision("create", NAME)
    assert created["status"] == "created"
    handle = created["avd"]["handle"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.synthetic_ui_actions import UiActionService\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobroot=Path(sys.argv[3])\n"
        "artroot=Path(sys.argv[4]);owner=sys.argv[5];artowner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "jobs=DurableJobStore(jobroot)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "art=PrivateArtifactStore(artroot)\n"
        "worker=UiActionService(avd,live,jobs,art,owner=owner,artifact_owner=artowner)\n"
        "create_server(ui_action_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[10]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            str(tmp_path / "jobs"),
            str(tmp_path / "private-audit"),
            OWNER,
            ART_OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def verify() -> None:
        last: Exception | None = None
        for _ in range(55):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {item.name: item for item in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_ui_action",
                    }
                    tool = tools["host_ui_action"]
                    schema = get_ui_action_schema()
                    assert tool.output_schema == schema
                    hints = tool.annotations.model_dump(mode="json", by_alias=True)
                    assert hints["readOnlyHint"] is False
                    assert hints["destructiveHint"] is True
                    assert hints["openWorldHint"] is False
                    assert "real ADB input stays disabled" in tool.description
                    request = {
                        "kind": "tap",
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                        "window_id": WINDOW,
                        "window_generation": GENERATION,
                        "rotation": ROTATION,
                        "focused_node_id": FOCUSED,
                        "x": 30,
                        "y": 40,
                    }
                    planned = await client.call_tool(
                        "host_ui_action", {"operation": "plan", **request}
                    )
                    assert planned.structured_content["status"] == "planned"
                    assert planned.structured_content["preview_argv"][0] == "fixture-ui-input"
                    result = await client.call_tool(
                        "host_ui_action", {"operation": "execute", **request, "request_id": REQUEST}
                    )
                    assert not result.is_error
                    denied = result.structured_content
                    Draft202012Validator(schema).validate(denied)
                    assert denied["status"] == "blocked"
                    assert denied["errors"][0]["code"] == "MUTATION_DISABLED"
                    assert denied["report_handle"] is None
                    assert denied["real_ui_input_enabled"] is False
                    assert denied["physical_device_writes_enabled"] is False
                    output = json.dumps(denied)
                    assert str(tmp_path) not in output
                    assert OWNER not in output
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"UI action localhost MCP unavailable: {type(last).__name__}")

    try:
        asyncio.run(verify())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    assert process.poll() is not None

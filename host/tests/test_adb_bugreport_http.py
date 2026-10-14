"""H5.a production plan-only CLI and true localhost MCP denial contracts."""

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
from test_adb_bugreport_artifacts import ART_OWNER, RAW, REQ, builder
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.synthetic_bugreport import BugreportService, get_bugreport_schema


def flags(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "private-bugreports"),
        "--artifact-owner",
        ART_OWNER,
        "--bugreport-plan",
    ]


def test_production_CLI_defaults_disabled_and_opt_in_has_no_reader(
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
            ["serve", "--bugreport-plan"],
            ["serve", "--bugreport-plan", "--avd-provision"],
            ["serve", "--bugreport-plan", "--artifact-metadata"],
            ["serve", "--bugreport-plan", "--durable-job-status"],
        ):
            with pytest.raises(SystemExit) as denied:
                cli.main(invalid)
            assert denied.value.code == 2
            assert calls == []
        assert cli.main(flags(tmp_path)) == 0
        assert len(calls) == 1
        worker = calls[0]["bugreport_worker"]
        assert isinstance(worker, BugreportService)
        assert worker._owner == OWNER
        assert worker._artifact_owner == ART_OWNER
        assert worker._fixture is None
        assert worker._approval is None
    assert not (tmp_path / "owned-avds").exists()


def test_cli_rejects_cross_owner_before_any_file_or_bugreport_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = flags(tmp_path)
    args[args.index("--job-owner") + 1] = "other-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as denied:
            cli.main(args)
    assert denied.value.code == 2
    assert not (tmp_path / "private-bugreports").exists()
    assert not (tmp_path / "owned-avds").exists()


def test_actual_inprocess_MCP_positive_receipt_is_sanitized_metadata_only(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    async def verify() -> None:
        async with Client(cli.create_server(bugreport_worker=worker)) as client:
            response = await client.call_tool(
                "host_bugreport",
                {
                    "action": "collect",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "request_id": REQ,
                },
            )
            assert not response.is_error
            receipt = response.structured_content
            Draft202012Validator(get_bugreport_schema()).validate(receipt)
            assert receipt["status"] == "ok"
            assert receipt["artifact_handle"].startswith("art_")
            assert receipt["receipt_handle"].startswith("art_")
            assert receipt["redacted_lines"] == 3
            assert receipt["retention_seconds"] == 120
            assert receipt["sanitized_only"] is True
            assert receipt["real_bugreport_enabled"] is False
            payload = json.dumps(receipt)
            assert RAW.decode("utf-8") not in payload
            assert "user@example.com" not in payload
            assert str(tmp_path) not in payload

    try:
        asyncio.run(verify())
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_real_localhost_Streamable_HTTP_MCP_default_denies_diagnostic_read(
    tmp_path: Path,
) -> None:
    created_provider = provider(tmp_path)
    result = created_provider.provision("create", NAME)
    assert result["status"] == "created"
    handle = result["avd"]["handle"]
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
        "from android_mcp_host.synthetic_bugreport import BugreportService\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobroot=Path(sys.argv[3])\n"
        "artroot=Path(sys.argv[4]);owner=sys.argv[5];artowner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "jobs=DurableJobStore(jobroot)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "art=PrivateArtifactStore(artroot)\n"
        "worker=BugreportService(avd,live,jobs,art,owner=owner,artifact_owner=artowner)\n"
        "create_server(bugreport_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[10]))\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            str(tmp_path / "jobs"),
            str(tmp_path / "private-bugreport"),
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
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_bugreport",
                    }
                    tool = tools["host_bugreport"]
                    schema = get_bugreport_schema()
                    assert tool.output_schema == schema
                    hints = tool.annotations.model_dump(mode="json", by_alias=True)
                    assert hints["readOnlyHint"] is False
                    assert hints["destructiveHint"] is True
                    assert hints["openWorldHint"] is False
                    assert "synthetic" in tool.description.lower()
                    target = {
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                    }
                    plan = await client.call_tool(
                        "host_bugreport",
                        {"action": "plan", **target},
                    )
                    assert plan.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_bugreport",
                        {"action": "collect", "request_id": REQ, **target},
                    )
                    assert not denied.is_error
                    reply = denied.structured_content
                    Draft202012Validator(schema).validate(reply)
                    assert reply["status"] == "blocked"
                    assert reply["errors"][0]["code"] == "CONSENT_REQUIRED"
                    assert reply["artifact_handle"] is None
                    assert reply["real_bugreport_enabled"] is False
                    assert reply["raw_content_returned"] is False
                    output = json.dumps(reply)
                    assert str(tmp_path) not in output
                    assert "user@example.com" not in output
                    assert OWNER not in output
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Private bugreport HTTP unavailable: {type(last).__name__}")

    try:
        asyncio.run(verify())
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    assert child.poll() is not None

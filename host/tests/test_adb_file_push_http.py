"""H4.e plan-only CLI and real localhost Streamable HTTP MCP contract."""

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
from test_adb_file_push_policy import ART_OWNER, DATA, DEST, MIME, PACKAGE, REQ, SHA, builder
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.server import create_server
from android_mcp_host.synthetic_file_push import FilePushService, get_file_push_schema


def flags(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "private-import-store"),
        "--artifact-owner",
        ART_OWNER,
        "--file-push-plan",
        "--file-push-package-id",
        PACKAGE,
    ]


def test_cli_plan_only_requires_explicit_trusted_operator_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **args: calls.append(args) or Stub())
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        invalid = (
            ["serve", "--file-push-plan"],
            ["serve", "--file-push-package-id", PACKAGE],
            ["serve", "--file-push-plan", "--file-push-package-id", PACKAGE],
            ["serve", "--file-push-plan", "--file-push-package-id", "com.example.real"],
            ["serve", "--file-push-plan", "--file-push-package-id", "../traversal"],
            ["serve", "--file-push-plan", "--avd-provision"],
        )
        for item in invalid:
            with pytest.raises(SystemExit) as exception:
                cli.main(item)
            assert exception.value.code == 2
            assert calls == []
        assert cli.main(flags(tmp_path)) == 0
        assert len(calls) == 1
        worker = calls[0]["file_push_worker"]
        assert isinstance(worker, FilePushService)
        assert worker._owner == OWNER
        assert worker._artifact_owner == ART_OWNER
        assert worker._package == PACKAGE
        assert worker._writer is None
        assert worker._approval is None
        assert worker._key is None
    assert not (tmp_path / "owned-avds").exists()


def test_file_push_cli_owner_mismatch_denied_before_file_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = flags(tmp_path)
    arguments[arguments.index("--job-owner") + 1] = "foreign"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as failure:
            cli.main(arguments)
    assert failure.value.code == 2
    assert not (tmp_path / "private-import-store").exists()
    assert not (tmp_path / "owned-avds").exists()


def test_in_process_mcp_synthetic_mutation_receipt_has_no_raw_content(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, token, fs = builder(tmp_path)

    async def verify() -> None:
        async with Client(create_server(file_push_worker=worker)) as client:
            result = await client.call_tool(
                "host_file_push",
                {
                    "action": "push",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "artifact_handle": token,
                    "artifact_sha256": SHA,
                    "destination_path": DEST,
                    "mime_type": MIME,
                    "request_id": REQ,
                },
            )
            assert not result.is_error
            data = result.structured_content
            Draft202012Validator(get_file_push_schema()).validate(data)
            assert data["status"] == "simulated"
            assert data["bytes_written"] == len(DATA)
            assert data["report_handle"].startswith("art_")
            assert data["report_sha256"]
            assert data["real_push_enabled"] is False
            assert data["physical_device_writes_enabled"] is False
            payload = json.dumps(data)
            assert DEST not in payload
            assert DATA.decode("utf-8") not in payload
            assert str(tmp_path) not in payload

    try:
        asyncio.run(verify())
        assert fs == {DEST: DATA}
    finally:
        live.shutdown()


def test_localhost_real_streamable_mcp_is_plan_only_no_backend_or_hmac(
    tmp_path: Path,
) -> None:
    own = provider(tmp_path)
    created = own.provision("create", NAME)
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
        "from android_mcp_host.synthetic_file_push import FilePushService\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jroot=Path(sys.argv[3])\n"
        "aroot=Path(sys.argv[4]);owner=sys.argv[5];artowner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "jobs=DurableJobStore(jroot)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "art=PrivateArtifactStore(aroot)\n"
        "worker=FilePushService(avd,live,jobs,art,owner=owner,"
        "artifact_owner=artowner,package_id=sys.argv[10])\n"
        "create_server(file_push_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[11]))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            str(tmp_path / "jobs"),
            str(tmp_path / "private-artifacts"),
            OWNER,
            ART_OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            PACKAGE,
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
                        "host_file_push",
                    }
                    tool = tools["host_file_push"]
                    schema = get_file_push_schema()
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
                        "artifact_handle": "art_" + "x" * 32,
                        "artifact_sha256": SHA,
                        "destination_path": DEST,
                    }
                    planned = await client.call_tool("host_file_push", {"action": "plan", **target})
                    assert planned.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_file_push", {"action": "push", **target, "request_id": REQ}
                    )
                    assert not denied.is_error
                    data = denied.structured_content
                    Draft202012Validator(schema).validate(data)
                    assert data["status"] == "blocked"
                    assert data["errors"][0]["code"] == "MUTATION_DISABLED"
                    assert data["report_handle"] is None
                    assert data["real_push_enabled"] is False
                    assert data["physical_device_writes_enabled"] is False
                    payload = json.dumps(data)
                    assert str(tmp_path) not in payload
                    assert DEST not in payload
                    assert OWNER not in payload
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(
            f"Private synthetic file-import HTTP unavailable: {type(last).__name__}"
        )

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

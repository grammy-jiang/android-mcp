"""H4.d default-denied CLI and actual localhost Streamable HTTP MCP contracts."""

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
from test_adb_file_pull_policy import (
    ART_OWNER,
    DIGEST,
    FILE,
    MIME,
    PACKAGE,
    REMOTE,
    REQUEST,
    builder,
)
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.synthetic_file_pull import FilePullService, get_file_pull_schema


def cli_flags(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "private-export-artifacts"),
        "--artifact-owner",
        ART_OWNER,
        "--file-pull-plan",
        "--file-pull-package-id",
        PACKAGE,
    ]


def test_cli_only_exposes_plan_with_no_real_file_reader(
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
        for args in (
            ["serve", "--file-pull-plan"],
            ["serve", "--file-pull-package-id", PACKAGE],
            ["serve", "--file-pull-plan", "--file-pull-package-id", PACKAGE],
            ["serve", "--file-pull-plan", "--file-pull-package-id", "com.real.user"],
            ["serve", "--file-pull-plan", "--file-pull-package-id", "../traversal"],
            ["serve", "--file-pull-plan", "--avd-provision"],
        ):
            with pytest.raises(SystemExit) as denied:
                cli.main(args)
            assert denied.value.code == 2
            assert calls == []
        assert cli.main(cli_flags(tmp_path)) == 0
        assert len(calls) == 1
        worker = calls[0]["file_pull_worker"]
        assert isinstance(worker, FilePullService)
        assert worker._fixture is None
        assert worker._approval is None
        assert worker._owner == OWNER
        assert worker._artifact_owner == ART_OWNER
        assert worker._package == PACKAGE
    assert not (tmp_path / "owned-avds").exists()


def test_cross_owner_file_pull_cli_rejects_before_storage_or_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = cli_flags(tmp_path)
    args[args.index("--job-owner") + 1] = "other-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as denied:
            cli.main(args)
    assert denied.value.code == 2
    assert not (tmp_path / "owned-avds").exists()
    assert not (tmp_path / "private-export-artifacts").exists()


def test_real_in_process_fastmcp_is_redacted_and_schema_checked(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid = builder(tmp_path)

    async def inspect() -> None:
        async with Client(cli.create_server(file_pull_worker=worker)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert "host_file_pull" in tools
            response = await client.call_tool(
                "host_file_pull",
                {
                    "action": "pull",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "remote_path": REMOTE,
                    "expected_sha256": DIGEST,
                    "mime_type": MIME,
                    "request_id": REQUEST,
                },
            )
            assert not response.is_error
            payload = response.structured_content
            Draft202012Validator(get_file_pull_schema()).validate(payload)
            assert payload["status"] == "ok"
            assert payload["filename"] == "report.json"
            assert payload["sha256"] == DIGEST
            assert payload["artifact_handle"].startswith("art_")
            assert REMOTE not in json.dumps(payload)
            assert FILE.decode("utf-8") not in json.dumps(payload)
            assert str(tmp_path) not in json.dumps(payload)

    try:
        asyncio.run(inspect())
    finally:
        live.shutdown()


def test_real_localhost_mcp_default_exposes_no_device_file_data(
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
        "from android_mcp_host.synthetic_file_pull import FilePullService\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobsroot=Path(sys.argv[3])\n"
        "artroot=Path(sys.argv[4]);owner=sys.argv[5];artowner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "jobs=DurableJobStore(jobsroot)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "art=PrivateArtifactStore(artroot)\n"
        "worker=FilePullService(avd,live,jobs,art,owner=owner,"
        "artifact_owner=artowner,package_id=sys.argv[10])\n"
        "create_server(file_pull_worker=worker).run("
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
            str(tmp_path / "private-metadata"),
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
        previous: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {t.name: t for t in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_file_pull",
                    }
                    tool = tools["host_file_pull"]
                    assert tool.output_schema == get_file_pull_schema()
                    hints = tool.annotations.model_dump(mode="json", by_alias=True)
                    assert hints["readOnlyHint"] is False
                    assert hints["destructiveHint"] is True
                    assert hints["openWorldHint"] is False
                    assert "sensitive" in tool.description.lower()
                    request = {
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                        "remote_path": REMOTE,
                    }
                    plan = await client.call_tool("host_file_pull", {"action": "plan", **request})
                    assert plan.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_file_pull",
                        {
                            "action": "pull",
                            **request,
                            "expected_sha256": DIGEST,
                            "mime_type": MIME,
                            "request_id": REQUEST,
                        },
                    )
                    assert not denied.is_error
                    value = denied.structured_content
                    Draft202012Validator(get_file_pull_schema()).validate(value)
                    assert value["status"] == "blocked"
                    assert value["errors"][0]["code"] == "CONSENT_REQUIRED"
                    assert value["artifact_handle"] is None
                    assert value["real_pull_enabled"] is False
                    assert value["raw_content_returned"] is False
                    serialized = json.dumps(value)
                    assert str(tmp_path) not in serialized
                    assert OWNER not in serialized
                    assert REMOTE not in serialized
                    assert FILE.decode() not in serialized
                    return
            except Exception as error:
                previous = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Private export HTTP contract unavailable: {type(previous).__name__}")

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

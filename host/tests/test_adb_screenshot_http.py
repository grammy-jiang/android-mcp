"""H4.a CLI denial gates and actual localhost Streamable HTTP contract."""

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
from test_adb_screenshot_artifacts import ART_OWNER, REQ
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_debug_http import cli_args

from android_mcp_host import cli
from android_mcp_host.synthetic_screenshot import ScreenshotArtifacts, get_screenshot_schema


def test_screenshot_cli_requires_trusted_prerequisites_and_has_no_real_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class StubServer:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def fake_server(**kwargs: Any) -> StubServer:
        calls.append(kwargs)
        return StubServer()

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", fake_server)
        for invalid in (
            ["serve", "--screenshot-plan"],
            ["serve", "--screenshot-plan", "--avd-provision"],
            ["serve", "--screenshot-plan", "--artifact-metadata"],
        ):
            with pytest.raises(SystemExit) as err:
                cli.main(invalid)
            assert err.value.code == 2
        assert not calls
        assert cli.main([*cli_args(tmp_path), "--screenshot-plan"]) == 0
        assert len(calls) == 1
        worker = calls[0]["screenshot_worker"]
        assert isinstance(worker, ScreenshotArtifacts)
        assert worker._fixture is None
        assert worker._approval is None
        assert calls[0]["debug_deployment"]._runner is None


def test_actual_localhost_mcp_screenshot_schema_and_denial(
    tmp_path: Path,
) -> None:
    owner = provider(tmp_path)
    created = owner.provision("create", NAME)
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
        "from android_mcp_host.synthetic_screenshot import ScreenshotArtifacts\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobs_root=Path(sys.argv[3])\n"
        "art_root=Path(sys.argv[4]);owner=sys.argv[5];art_owner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "jobs=DurableJobStore(jobs_root)\n"
        "live=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "art=PrivateArtifactStore(art_root)\n"
        "worker=ScreenshotArtifacts(avd,live,jobs,art,owner=owner,artifact_owner=art_owner)\n"
        "create_server(screenshot_worker=worker).run("
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
            str(tmp_path / "private-http-artifacts"),
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
        for _ in range(45):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_screenshot",
                    }
                    tool = tools["host_screenshot"]
                    schema = get_screenshot_schema()
                    assert tool.output_schema == schema
                    assert "sensitive" in tool.description.lower()
                    assert tool.annotations.readOnlyHint is False
                    assert tool.annotations.destructiveHint is True
                    args = {
                        "action": "plan",
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                    }
                    plan = await client.call_tool("host_screenshot", args)
                    assert plan.structured_content["status"] == "planned"
                    denial = await client.call_tool(
                        "host_screenshot",
                        {**args, "action": "capture", "request_id": REQ},
                    )
                    assert not denial.is_error
                    response = denial.structured_content
                    Draft202012Validator(schema).validate(response)
                    assert response["status"] == "blocked"
                    assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
                    assert response["artifact_handle"] is None
                    assert response["real_capture_enabled"] is False
                    payload = json.dumps(response)
                    assert ART_OWNER not in payload
                    assert str(tmp_path) not in payload
                    assert "iVBOR" not in payload
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic screenshot HTTP contract unavailable: {last!r}")

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

"""H3.f production opt-in and actual local HTTP synthetic deployment contract."""

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
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_debug_deployment import (
    APK_MIME,
    ARTIFACT_OWNER,
    PACKAGE,
    REQ,
    fixture_apk,
)
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.emulator_debug_deployment import DebugDeployment, get_debug_deploy_schema
from android_mcp_host.private_artifact_store import PrivateArtifactStore


def cli_args(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "private-artifacts"),
        "--artifact-owner",
        ARTIFACT_OWNER,
        "--emulator-debug-plan",
        "--debug-package-id",
        PACKAGE,
    ]


def test_cli_inert_debug_tool_requires_all_operator_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def factory(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", factory)
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for argv in (
            ["serve", "--emulator-debug-plan"],
            ["serve", "--debug-package-id", PACKAGE],
            ["serve", "--emulator-debug-plan", "--debug-package-id", PACKAGE],
            ["serve", "--emulator-debug-plan", "--debug-package-id", "../../unsafe"],
            [
                "serve",
                "--emulator-debug-plan",
                "--debug-package-id",
                "org.example.synthetic.bad/evil",
            ],
        ):
            with pytest.raises(SystemExit) as error:
                cli.main(argv)
            assert error.value.code == 2
            assert calls == []
        assert cli.main(cli_args(tmp_path)) == 0
        assert len(calls) == 1
        deployment = calls[0]["debug_deployment"]
        assert isinstance(deployment, DebugDeployment)
        assert deployment._runner is None
        assert deployment._owner == OWNER
        assert deployment._artifact_owner == ARTIFACT_OWNER
        assert deployment._package == PACKAGE
    assert not (tmp_path / "owned-avds").exists()


def test_cross_owner_rejected_by_cli_before_creating_private_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = cli_args(tmp_path)
    args[args.index("--job-owner") + 1] = "other-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as error:
            cli.main(args)
    assert error.value.code == 2
    assert not (tmp_path / "jobs").exists()
    assert not (tmp_path / "owned-avds").exists()


def test_real_localhost_http_debug_tool_never_installs_to_physical_or_fake_device(
    tmp_path: Path,
) -> None:
    owner = provider(tmp_path)
    record = owner.provision("create", NAME)
    assert record["status"] == "created"
    avd_handle = record["avd"]["handle"]
    store = PrivateArtifactStore(tmp_path / "private-debug-artifacts")
    apk_bytes = fixture_apk(tmp_path)
    apk_handle = store.put(ARTIFACT_OWNER, apk_bytes, mime_type=APK_MIME)["handle"]
    digest = hashlib.sha256(apk_bytes).hexdigest()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.emulator_debug_deployment import DebugDeployment\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobs_root=Path(sys.argv[3])\n"
        "art_root=Path(sys.argv[4]);owner=sys.argv[5];art_owner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "ledger=DurableJobStore(jobs_root)\n"
        "live=EmulatorLifecycle(avd,ledger,owner=owner)\n"
        "artifacts=PrivateArtifactStore(art_root)\n"
        "worker=DebugDeployment(avd,live,ledger,artifacts,owner=owner,"
        "artifact_owner=art_owner,expected_package=sys.argv[10])\n"
        "create_server(debug_deployment=worker).run("
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
            str(tmp_path / "private-debug-artifacts"),
            OWNER,
            ARTIFACT_OWNER,
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
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    names = {tool.name for tool in await client.list_tools()}
                    assert names == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_emulator_debug_deploy",
                    }
                    request = {
                        "action": "plan",
                        "avd_name": NAME,
                        "avd_handle": avd_handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                        "apk_handle": apk_handle,
                        "apk_sha256": digest,
                        "package_id": PACKAGE,
                    }
                    plan = await client.call_tool("host_emulator_debug_deploy", request)
                    assert not plan.is_error
                    assert plan.structured_content["status"] == "planned"
                    assert plan.structured_content["real_deployment_enabled"] is False
                    Draft202012Validator(get_debug_deploy_schema()).validate(
                        plan.structured_content
                    )
                    for action in ("install", "launch", "uninstall", "cleanup"):
                        attempted = await client.call_tool(
                            "host_emulator_debug_deploy",
                            {**request, "action": action, "request_id": REQ},
                        )
                        result = attempted.structured_content
                        assert result["status"] == "blocked"
                        assert result["real_deployment_enabled"] is False
                        assert result["physical_device_writes_enabled"] is False
                        assert str(tmp_path) not in json.dumps(result)
                    return
            except (OSError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Local debug Tool unavailable: {type(last).__name__}")

    try:
        asyncio.run(verify())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None

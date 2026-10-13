"""Production H3.e disabled-by-default CLI and isolated localhost MCP contracts."""

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
from test_emulator_instrumentation_jobs import (
    APK_MIME,
    COMPONENT,
    INSTRUMENT_OWNER,
    RUN_REQUEST,
    synthetic_test_apk,
)
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.emulator_instrumentation_jobs import (
    InstrumentationJobs,
    get_instrumentation_schema,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore


def test_default_host_cli_has_no_instrumentation_provider(
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
        patch.setattr(cli, "create_server", factory)
        patch.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        with pytest.raises(SystemExit) as error:
            cli.main(["serve", "--emulator-instrumentation-plan"])
        assert error.value.code == 2
        assert not calls
        full = [
            *make_flags(tmp_path),
            "--artifact-metadata",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--artifact-owner",
            INSTRUMENT_OWNER,
        ]
        assert cli.main([*full, "--emulator-instrumentation-plan"]) == 0
        assert len(calls) == 1
        work = calls[0]["instrumentation_jobs"]
        assert isinstance(work, InstrumentationJobs)
        assert work._runner is None
        assert work._owner == OWNER
        assert work._artifact_owner == INSTRUMENT_OWNER
    assert not (tmp_path / "owned-avds").exists()


def test_cli_rejects_owner_mismatch_and_missing_required_private_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags = [*make_flags(tmp_path), "--emulator-instrumentation-plan"]
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as missing:
            cli.main(flags)
        assert missing.value.code == 2
        args = [
            *flags,
            "--artifact-metadata",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--artifact-owner",
            INSTRUMENT_OWNER,
        ]
        args[args.index("--job-owner") + 1] = "wrong-owner"
        with pytest.raises(SystemExit) as mismatched:
            cli.main(args)
        assert mismatched.value.code == 2
    assert not (tmp_path / "owned-avds").exists()
    assert not (tmp_path / "jobs").exists()


def test_real_localhost_mcp_exposes_only_inert_instrumentation_plan(
    tmp_path: Path,
) -> None:
    owner = provider(tmp_path)
    record = owner.provision("create", NAME)
    assert record["status"] == "created"
    avd_handle = record["avd"]["handle"]
    artifacts = PrivateArtifactStore(tmp_path / "private-artifacts")
    apk = synthetic_test_apk()
    apk_handle = artifacts.put(INSTRUMENT_OWNER, apk, mime_type=APK_MIME)["handle"]
    digest = hashlib.sha256(apk).hexdigest()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.emulator_instrumentation_jobs import InstrumentationJobs\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "root=Path(sys.argv[1]); sdk=Path(sys.argv[2]); job_root=Path(sys.argv[3])\n"
        "object_root=Path(sys.argv[4]); owner=sys.argv[5]; art_owner=sys.argv[6]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[7],"
        "system_image_sha256=sys.argv[8],license_sha256=sys.argv[9])\n"
        "ledger=DurableJobStore(job_root)\n"
        "lifecycle=EmulatorLifecycle(avd,ledger,owner=owner)\n"
        "artifacts=PrivateArtifactStore(object_root)\n"
        "jobs=InstrumentationJobs(avd,lifecycle,ledger,artifacts,"
        "owner=owner,artifact_owner=art_owner)\n"
        "create_server(instrumentation_jobs=jobs).run("
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
            str(tmp_path / "private-artifacts"),
            OWNER,
            INSTRUMENT_OWNER,
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
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {tool.name for tool in await client.list_tools()}
                    assert catalog == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_emulator_instrumentation",
                    }
                    plan = await client.call_tool(
                        "host_emulator_instrumentation",
                        {
                            "action": "plan",
                            "avd_name": NAME,
                            "avd_handle": avd_handle,
                            "lifecycle_job_id": "job_" + "x" * 32,
                            "apk_handle": apk_handle,
                            "apk_sha256": digest,
                            "component": COMPONENT,
                        },
                    )
                    assert not plan.is_error
                    assert plan.structured_content["status"] == "planned"
                    assert plan.structured_content["real_instrumentation_enabled"] is False
                    Draft202012Validator(get_instrumentation_schema()).validate(
                        plan.structured_content
                    )
                    denied = await client.call_tool(
                        "host_emulator_instrumentation",
                        {
                            "action": "run",
                            "avd_name": NAME,
                            "avd_handle": avd_handle,
                            "lifecycle_job_id": "job_" + "x" * 32,
                            "apk_handle": apk_handle,
                            "apk_sha256": digest,
                            "component": COMPONENT,
                            "request_id": RUN_REQUEST,
                        },
                    )
                    assert denied.structured_content["status"] == "blocked"
                    assert str(tmp_path) not in json.dumps(denied.structured_content)
                    return
            except (OSError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Local instrumentation unavailable: {type(last).__name__}")

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

"""H5.c operator CLI and actual localhost Streamable HTTP privacy contracts."""

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
from test_emulator_lifecycle_cli import make_flags
from test_perfetto_trace_job import ART_OWNER, REQ, builder

from android_mcp_host import cli
from android_mcp_host.synthetic_perfetto import PerfettoService, get_perfetto_schema


def flags(tmp_path: Path) -> list[str]:
    return [
        *make_flags(tmp_path),
        "--artifact-metadata",
        "--artifact-root",
        str(tmp_path / "private-perfetto"),
        "--artifact-owner",
        ART_OWNER,
        "--perfetto-plan",
    ]


def test_cli_defaults_disabled_and_explicit_plan_never_injects_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **kw: calls.append(kw) or Stub())
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for bad in (
            ["serve", "--perfetto-plan"],
            ["serve", "--perfetto-plan", "--avd-provision"],
            ["serve", "--perfetto-plan", "--durable-job-status"],
            ["serve", "--perfetto-plan", "--artifact-metadata"],
        ):
            with pytest.raises(SystemExit) as denied:
                cli.main(bad)
            assert denied.value.code == 2
            assert calls == []
        assert cli.main(flags(tmp_path)) == 0
        assert len(calls) == 1
        worker = calls[0]["perfetto_worker"]
        assert isinstance(worker, PerfettoService)
        assert worker._owner == OWNER
        assert worker._artifact_owner == ART_OWNER
        assert worker._fixture is None
        assert worker._approval is None
    assert not (tmp_path / "owned-avds").exists()


def test_cli_denies_cross_owner_before_creating_sensitive_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = flags(tmp_path)
    args[args.index("--job-owner") + 1] = "wrong-owner"
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as denied:
            cli.main(args)
    assert denied.value.code == 2
    assert not (tmp_path / "private-perfetto").exists()
    assert not (tmp_path / "owned-avds").exists()


def test_fastmcp_negative_default_plan_denies_real_tracing(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(
        tmp_path,
        active=False,
        approved=False,
    )

    async def verify() -> None:
        async with Client(cli.create_server(perfetto_worker=worker)) as client:
            catalog = {x.name: x for x in await client.list_tools()}
            tool = catalog["host_perfetto_trace"]
            assert tool.output_schema == get_perfetto_schema()
            args = {"avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid}
            planned = await client.call_tool("host_perfetto_trace", {"action": "plan", **args})
            assert planned.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_perfetto_trace", {"action": "capture", "request_id": REQ, **args}
            )
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["errors"][0]["code"] == "CONSENT_REQUIRED"
            assert denied.structured_content["real_perfetto_enabled"] is False
            assert denied.structured_content["raw_trace_returned"] is False
            Draft202012Validator(get_perfetto_schema()).validate(denied.structured_content)

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()


def test_true_localhost_streamable_http_prod_denies_capture(tmp_path: Path) -> None:
    avd = provider(tmp_path)
    result = avd.provision("create", NAME)
    assert result["status"] == "created"
    handle = result["avd"]["handle"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    script = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.synthetic_perfetto import PerfettoService\n"
        "avd=AvdProvisioner(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[5],"
        "api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[6],"
        "system_image_sha256=sys.argv[7],"
        "license_sha256=sys.argv[8])\n"
        "jobs=DurableJobStore(Path(sys.argv[3]))\n"
        "live=EmulatorLifecycle(avd,jobs,owner=sys.argv[5])\n"
        "store=PrivateArtifactStore(Path(sys.argv[4]))\n"
        "worker=PerfettoService(avd,live,jobs,store,owner=sys.argv[5],"
        "artifact_owner=sys.argv[9])\n"
        "create_server(perfetto_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[10]))\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "owned-avds"),
            str(tmp_path / "synthetic-sdk"),
            str(tmp_path / "jobs"),
            str(tmp_path / "private-artifacts"),
            OWNER,
            hashlib.sha256(SOURCE).hexdigest(),
            hashlib.sha256(SYSTEM).hexdigest(),
            hashlib.sha256(LICENSE).hexdigest(),
            ART_OWNER,
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def verify() -> None:
        last: Exception | None = None
        for _ in range(70):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    tools = {x.name: x for x in await client.list_tools()}
                    assert set(tools) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_perfetto_trace",
                    }
                    tool = tools["host_perfetto_trace"]
                    assert tool.output_schema == get_perfetto_schema()
                    assert tool.annotations.destructive_hint is True
                    args = {
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                    }
                    plan = await client.call_tool("host_perfetto_trace", {"action": "plan", **args})
                    assert plan.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_perfetto_trace", {"action": "capture", "request_id": REQ, **args}
                    )
                    assert not denied.is_error
                    data = denied.structured_content
                    Draft202012Validator(get_perfetto_schema()).validate(data)
                    assert data["status"] == "blocked"
                    assert data["errors"][0]["code"] == "CONSENT_REQUIRED"
                    assert data["artifact_handle"] is None
                    assert str(tmp_path) not in json.dumps(data)
                    assert OWNER not in json.dumps(data)
                    assert data["raw_trace_returned"] is False
                    return
            except (OSError, ConnectionError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.05)
        raise AssertionError("Private localhost MCP unavailable") from last

    try:
        asyncio.run(verify())
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def test_true_localhost_mcp_positive_synthetic_trace_and_private_receipt(tmp_path: Path) -> None:
    """Fixture-enabled test process exposes a real HTTP Tool; no Android access."""
    fixture_root = tmp_path / "http-fixture-positive"
    fixture_root.mkdir()
    receipt = fixture_root / "target.json"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys,json,time\n"
        "sys.path.insert(0,str(Path(sys.argv[4]).resolve()))\n"
        "from test_avd_provisioning import NAME, OWNER\n"
        "from test_emulator_lifecycle_jobs import engine,REQUEST as START_REQUEST\n"
        "from test_perfetto_trace_job import ART_OWNER,RAW,frame\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.synthetic_perfetto import PerfettoApproval,PerfettoService\n"
        "from android_mcp_host.server import create_server\n"
        "live,handle,jobs,_=engine(Path(sys.argv[1]),readiness_timeout=5.0)\n"
        "status=live.run('start',NAME,handle,request_id=START_REQUEST)\n"
        "assert status['status']=='ok'\n"
        "lid=status['job_id']\n"
        "store=PrivateArtifactStore(Path(sys.argv[1])/'http-traces')\n"
        "grant=PerfettoApproval(OWNER,handle,lid,'sched-lite-v1',"
        "'private-synthetic-perfetto',time.time()+180,120,True,True)\n"
        "def fake(name,handle,lid,profile,duration,cap,timeout,stop):\n"
        "    return frame(RAW,name,handle,lid,profile,duration)\n"
        "worker=PerfettoService(live.provisioner,live,jobs,store,"
        "owner=OWNER,artifact_owner=ART_OWNER,approval=grant,fixture_trace=fake)\n"
        "Path(sys.argv[2]).write_text(json.dumps({'handle':handle,'lid':lid}))\n"
        "create_server(perfetto_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[3]))\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(fixture_root / "work"),
            str(receipt),
            str(port),
            str(Path(__file__).resolve().parent),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def check_http() -> None:
        last: Exception | None = None
        for _ in range(75):
            try:
                if not receipt.exists():
                    await asyncio.sleep(0.05)
                    continue
                identity = json.loads(receipt.read_text())
                args = {
                    "avd_name": NAME,
                    "avd_handle": identity["handle"],
                    "lifecycle_job_id": identity["lid"],
                }
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    captured = await client.call_tool(
                        "host_perfetto_trace",
                        {"action": "capture", "request_id": REQ, **args},
                    )
                    assert not captured.is_error
                    data = captured.structured_content
                    Draft202012Validator(get_perfetto_schema()).validate(data)
                    assert data["status"] == "ok"
                    assert data["trace_state"] == "synthetic_sanitized"
                    assert data["sample_count"] == 3
                    assert data["redacted_lines"] == 1
                    assert data["artifact_handle"].startswith("art_")
                    assert data["sha256"]
                    assert data["real_perfetto_enabled"] is False
                    assert data["raw_trace_returned"] is False
                    assert "private-user@example.com" not in json.dumps(data)
                    assert str(tmp_path) not in json.dumps(data)
                    replay = await client.call_tool(
                        "host_perfetto_trace",
                        {"action": "capture", "request_id": REQ, **args},
                    )
                    assert replay.structured_content["status"] == "ok"
                    assert replay.structured_content["job_id"] == data["job_id"]
                    assert replay.structured_content["artifact_handle"] == data["artifact_handle"]
                    denied = await client.call_tool(
                        "host_perfetto_trace",
                        {"action": "capture", "request_id": REQ, "duration_s": 4, **args},
                    )
                    assert denied.structured_content["status"] == "blocked"
                    assert denied.structured_content["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
                    return
            except (OSError, ConnectionError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.05)
        raise AssertionError("HTTP Perfetto fake fixture was unavailable") from last

    try:
        asyncio.run(check_http())
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)

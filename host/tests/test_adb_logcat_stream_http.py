"""H5.b true localhost Streamable HTTP and production CLI fail-closed checks."""

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
from test_adb_logcat_stream_jobs import REQ, builder
from test_avd_provisioning import LICENSE, NAME, OWNER, SOURCE, SYSTEM, provider
from test_emulator_lifecycle_cli import make_flags

from android_mcp_host import cli
from android_mcp_host.synthetic_logcat_stream import SyntheticLogcatStream, get_logcat_stream_schema


def flags(tmp_path: Path) -> list[str]:
    return [*make_flags(tmp_path), "--logcat-stream-plan"]


def test_production_cli_is_explicit_opt_in_and_never_injects_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        patch.setattr(cli, "create_server", lambda **kwargs: calls.append(kwargs) or Stub())
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for missing in (
            ["serve", "--logcat-stream-plan"],
            ["serve", "--logcat-stream-plan", "--avd-provision"],
            ["serve", "--logcat-stream-plan", "--durable-job-status"],
            ["serve", "--logcat-stream-plan", "--emulator-lifecycle-plan"],
        ):
            with pytest.raises(SystemExit) as denied:
                cli.main(missing)
            assert denied.value.code == 2
        assert calls == []
        assert cli.main(flags(tmp_path)) == 0
        assert len(calls) == 1
        worker = calls[0]["logcat_stream_worker"]
        assert isinstance(worker, SyntheticLogcatStream)
        assert worker._fixture is None
        assert worker._approval is None
        assert worker._owner == OWNER
    assert not (tmp_path / "owned-avds").exists()


def test_production_cli_denies_cross_owner_prior_to_private_file_creation(
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
    assert not (tmp_path / "owned-avds").exists()
    assert not (tmp_path / "private-jobs").exists()


def test_fastmcp_production_no_reader_has_typed_denial(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path, active=False, approved=False)

    async def check() -> None:
        async with Client(cli.create_server(logcat_stream_worker=worker)) as client:
            tools = {x.name: x for x in await client.list_tools()}
            tool = tools["host_logcat_stream"]
            assert tool.output_schema == get_logcat_stream_schema()
            args = {"avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid}
            plan = await client.call_tool("host_logcat_stream", {"action": "plan", **args})
            assert plan.structured_content["status"] == "planned"
            denied = await client.call_tool(
                "host_logcat_stream",
                {"action": "start", "request_id": REQ, **args},
            )
            Draft202012Validator(get_logcat_stream_schema()).validate(denied.structured_content)
            assert denied.structured_content["status"] == "blocked"
            assert denied.structured_content["errors"][0]["code"] == "CONSENT_REQUIRED"
            assert denied.structured_content["real_logcat_stream_enabled"] is False
            assert denied.structured_content["entries"] == []

    try:
        asyncio.run(check())
    finally:
        live.shutdown()


def test_true_localhost_http_denies_real_logcat_and_never_leaks_private_path(
    tmp_path: Path,
) -> None:
    avd = provider(tmp_path)
    owned = avd.provision("create", NAME)
    assert owned["status"] == "created"
    handle = owned["avd"]["handle"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys\n"
        "from android_mcp_host.server import create_server\n"
        "from android_mcp_host.avd_provisioning import AvdProvisioner\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.emulator_lifecycle import EmulatorLifecycle\n"
        "from android_mcp_host.synthetic_logcat_stream import SyntheticLogcatStream\n"
        "root=Path(sys.argv[1]);sdk=Path(sys.argv[2]);jobsroot=Path(sys.argv[3])\n"
        "owner=sys.argv[4]\n"
        "avd=AvdProvisioner(root,sdk,owner,api=36,abi='arm64-v8a',"
        "source_properties_sha256=sys.argv[5],"
        "system_image_sha256=sys.argv[6],license_sha256=sys.argv[7])\n"
        "jobs=DurableJobStore(jobsroot)\n"
        "life=EmulatorLifecycle(avd,jobs,owner=owner)\n"
        "worker=SyntheticLogcatStream(avd,life,jobs,owner=owner)\n"
        "create_server(logcat_stream_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[8]))\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
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

    async def verify() -> None:
        last: Exception | None = None
        for _ in range(55):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {t.name: t for t in await client.list_tools()}
                    assert set(catalog) == {
                        "device_status",
                        "adb_observe",
                        "adb_develop",
                        "host_logcat_stream",
                    }
                    tool = catalog["host_logcat_stream"]
                    assert tool.output_schema == get_logcat_stream_schema()
                    assert tool.annotations.destructive_hint is True
                    args = {
                        "avd_name": NAME,
                        "avd_handle": handle,
                        "lifecycle_job_id": "job_" + "z" * 32,
                    }
                    plan = await client.call_tool(
                        "host_logcat_stream",
                        {"action": "plan", **args},
                    )
                    assert plan.structured_content["status"] == "planned"
                    denied = await client.call_tool(
                        "host_logcat_stream",
                        {"action": "start", "request_id": REQ, **args},
                    )
                    reply = denied.structured_content
                    Draft202012Validator(get_logcat_stream_schema()).validate(reply)
                    assert reply["status"] == "blocked"
                    assert reply["errors"][0]["code"] == "CONSENT_REQUIRED"
                    assert reply["synthetic_fixture_only"] is True
                    assert reply["real_logcat_stream_enabled"] is False
                    assert reply["raw_logcat_returned"] is False
                    assert reply["entries"] == []
                    assert str(tmp_path) not in json.dumps(reply)
                    assert OWNER not in json.dumps(reply)
                    return
            except (OSError, ConnectionError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.05)
        raise AssertionError("Localhost MCP not ready") from last

    try:
        asyncio.run(verify())
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def test_true_localhost_http_successful_cursor_page_then_stop(tmp_path: Path) -> None:
    """Exercise actual MCP HTTP start/poll/stop, not only in-process adapters."""
    fixture_root = tmp_path / "http-positive"
    root = fixture_root / "owned"
    receipt = fixture_root / "session.json"
    fixture_root.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    program = (
        "from pathlib import Path\nimport sys,json,time\n"
        "sys.path.insert(0, str(Path(sys.argv[4]).resolve()))\n"
        "from test_avd_provisioning import NAME, OWNER\n"
        "from test_emulator_lifecycle_jobs import engine,REQUEST as START_REQUEST\n"
        "from test_adb_logcat_stream_jobs import RAW\n"
        "from android_mcp_host.synthetic_logcat_stream import "
        "StreamApproval,StreamFrame,SyntheticLogcatStream\n"
        "from android_mcp_host.server import create_server\n"
        "live,handle,jobs,_=engine(Path(sys.argv[1]),readiness_timeout=5.0)\n"
        "state=live.run('start',NAME,handle,request_id=START_REQUEST)\n"
        "assert state['status']=='ok'\n"
        "lid=state['job_id']\n"
        "grant=StreamApproval(OWNER,handle,lid,'synthetic-sanitized-logcat',time.time()+115,60)\n"
        "def fake(name,handle,lid,max_events,max_bytes,timeout,stop):\n"
        "    return StreamFrame(RAW,name,handle,lid,True,True)\n"
        "worker=SyntheticLogcatStream(live.provisioner,live,jobs,owner=OWNER,"
        "approval=grant,fixture_read=fake)\n"
        "Path(sys.argv[2]).write_text(json.dumps({'handle':handle,'lid':lid}))\n"
        "create_server(logcat_stream_worker=worker).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[3]))\n"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(root),
            str(receipt),
            str(port),
            str(Path(__file__).resolve().parent),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def verify() -> None:
        last: Exception | None = None
        for _ in range(75):
            try:
                if not receipt.exists():
                    await asyncio.sleep(0.05)
                    continue
                info = json.loads(receipt.read_text())
                base = {
                    "avd_name": NAME,
                    "avd_handle": info["handle"],
                    "lifecycle_job_id": info["lid"],
                    "request_id": REQ,
                }
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    start = await client.call_tool(
                        "host_logcat_stream",
                        {"action": "start", **base},
                    )
                    assert not start.is_error
                    first = start.structured_content
                    assert first["status"] == "ok"
                    assert first["cursor"] is not None
                    poll = await client.call_tool(
                        "host_logcat_stream",
                        {
                            "action": "poll",
                            "job_id": first["job_id"],
                            "cursor": first["cursor"],
                            "page_size": 2,
                            **base,
                        },
                    )
                    page = poll.structured_content
                    assert page["status"] == "ok"
                    assert page["from_index"] == 0
                    assert page["next_index"] == 2
                    assert page["entries"][0]["message"] == "STATE=ready"
                    assert "private-secret" not in json.dumps(page)
                    again = await client.call_tool(
                        "host_logcat_stream",
                        {
                            "action": "poll",
                            "job_id": first["job_id"],
                            "cursor": first["cursor"],
                            "page_size": 2,
                            **base,
                        },
                    )
                    assert again.structured_content["errors"][0]["code"] == "CURSOR_CONFLICT"
                    stopped = await client.call_tool(
                        "host_logcat_stream",
                        {
                            "action": "stop",
                            "job_id": first["job_id"],
                            **base,
                        },
                    )
                    assert stopped.structured_content["status"] == "stopped"
                    after = await client.call_tool(
                        "host_logcat_stream",
                        {
                            "action": "poll",
                            "job_id": first["job_id"],
                            "cursor": page["cursor"],
                            **base,
                        },
                    )
                    assert after.structured_content["errors"][0]["code"] == "STOPPED"
                    return
            except (OSError, ConnectionError, RuntimeError) as error:
                last = error
                await asyncio.sleep(0.05)
        raise AssertionError("Positive synthetic Streamable HTTP not ready") from last

    try:
        asyncio.run(verify())
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)

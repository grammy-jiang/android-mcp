"""H2.d Host-only opt-in, localhost Tool contract and real SQLite worker race."""

from __future__ import annotations

import asyncio
import json
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_host_durable_jobs import IDENTITY, OWNER, PLAN, RESULT, WORKER

from android_mcp_host import cli
from android_mcp_host.durable_jobs import DurableJobStore, get_job_status_schema
from android_mcp_host.server import create_server


def create_store(tmp_path: Path) -> DurableJobStore:
    return DurableJobStore(tmp_path / "private-jobs")


def create_job(store: DurableJobStore, name: str, *, queued: bool = False) -> str:
    job_id = store.prepare(OWNER, name, PLAN, identity=IDENTITY, authorized=True)["job_id"]
    if queued:
        store.queue(OWNER, job_id, identity=IDENTITY, authorized=True)
    return str(job_id)


def test_public_cli_default_off_requires_root_and_host_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    def make(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as scoped:
        scoped.setattr(cli, "create_server", make)
        scoped.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for argv in (
            ["serve", "--job-root", str(tmp_path / "root")],
            ["serve", "--job-owner", OWNER],
            ["serve", "--durable-job-status"],
            ["serve", "--durable-job-status", "--job-root", str(tmp_path / "root")],
            ["serve", "--durable-job-status", "--job-root", "relative/root", "--job-owner", OWNER],
            [
                "serve",
                "--durable-job-status",
                "--job-root",
                str(tmp_path / "root"),
                "--job-owner",
                "../injected",
            ],
        ):
            with pytest.raises(SystemExit) as error:
                cli.main(argv)
            assert error.value.code == 2
            assert calls == []
        assert not (tmp_path / "root").exists()
        assert (
            cli.main(
                [
                    "serve",
                    "--durable-job-status",
                    "--job-root",
                    str(tmp_path / "private-jobs"),
                    "--job-owner",
                    OWNER,
                ]
            )
            == 0
        )

    assert len(calls) == 1
    assert calls[0]["job_owner"] == OWNER
    assert isinstance(calls[0]["durable_jobs"], DurableJobStore)
    assert calls[0]["durable_jobs"].list_status(OWNER) == []
    assert stat.S_IMODE((tmp_path / "private-jobs").stat().st_mode) == 0o700


def test_server_fails_closed_when_only_one_provider_scope_or_bad_owner(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    with pytest.raises(ValueError, match="trusted store"):
        create_server(durable_jobs=store)
    with pytest.raises(ValueError, match="trusted store"):
        create_server(job_owner=OWNER)
    with pytest.raises(ValueError, match="Invalid Host job owner"):
        create_server(durable_jobs=store, job_owner="other/owner")


def test_public_poll_all_synthetic_states_are_json_schema_valid(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    names = (
        "prepared",
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "uncertain",
    )
    job_ids: dict[str, str] = {}
    for state in names:
        job_ids[state] = create_job(store, f"job-{state}", queued=state != "prepared")
        current = job_ids[state]
        if state in {"running", "succeeded", "failed", "uncertain"}:
            store.claim(OWNER, current, WORKER, IDENTITY, authorized=True)
        if state == "succeeded":
            store.complete(
                OWNER,
                current,
                WORKER,
                1,
                IDENTITY,
                authorized=True,
                result_digest=RESULT,
            )
        elif state == "failed":
            store.complete(
                OWNER,
                current,
                WORKER,
                1,
                IDENTITY,
                authorized=True,
                failure_code="FIXTURE_FAILED",
            )
        elif state == "cancelled":
            store.cancel(OWNER, current, identity=IDENTITY, authorized=True)
        elif state == "uncertain":
            store.cancel(OWNER, current, identity=IDENTITY, authorized=True)

    async def check() -> None:
        async with Client(create_server(durable_jobs=store, job_owner=OWNER)) as client:
            for state, handle in job_ids.items():
                response = await client.call_tool("host_job_status", {"job_id": handle})
                assert not response.is_error
                payload = response.structured_content
                assert isinstance(payload, dict)
                Draft202012Validator(get_job_status_schema()).validate(payload)
                assert payload["job"]["state"] == state
                assert payload["job"]["execution_enabled"] is False
                assert OWNER not in json.dumps(payload)
                assert IDENTITY not in json.dumps(payload)
                assert str(tmp_path) not in json.dumps(payload)

    asyncio.run(check())


def test_public_poll_through_real_loopback_host_process(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    job_id = create_job(store, "http-request", queued=True)
    root = tmp_path / "private-jobs"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    program = (
        "from pathlib import Path\n"
        "import sys\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.server import create_server\n"
        "provider=DurableJobStore(Path(sys.argv[1]))\n"
        "create_server(durable_jobs=provider,job_owner=sys.argv[2]).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[3]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(root), OWNER, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def poll() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    listed = {tool.name: tool for tool in await client.list_tools()}
                    assert "host_job_status" in listed
                    reply = await client.call_tool("host_job_status", {"job_id": job_id})
                    assert not reply.is_error
                    assert isinstance(reply.structured_content, dict)
                    Draft202012Validator(listed["host_job_status"].output_schema).validate(
                        reply.structured_content
                    )
                    assert reply.structured_content["job"]["state"] == "queued"
                    assert reply.structured_content["job"]["execution_enabled"] is False
                    assert str(root) not in json.dumps(reply.structured_content)
                    unknown = await client.call_tool(
                        "host_job_status", {"job_id": "job_" + "0" * 32}
                    )
                    assert unknown.structured_content["status"] == "not_found"
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic H2.d localhost HTTP failed: {last!r}")

    try:
        asyncio.run(poll())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None


def test_two_separate_processes_race_for_only_one_job(tmp_path: Path) -> None:
    """Cross-process SQLite BEGIN IMMEDIATE elects exactly one worker."""
    store = create_store(tmp_path)
    job_id = create_job(store, "race-process-request", queued=True)
    root = tmp_path / "private-jobs"
    code = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "from android_mcp_host.durable_jobs import DurableJobStore,JobStoreError\n"
        "store=DurableJobStore(Path(sys.argv[1]))\n"
        "try:\n"
        " res=store.claim(sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5],authorized=True)\n"
        " print(json.dumps({'result':res['state'],'attempts':res['attempts']}))\n"
        "except JobStoreError as error:\n"
        " print(json.dumps({'result':error.code}))\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(root), OWNER, job_id, f"worker-{i}", IDENTITY],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(4)
    ]
    try:
        results = []
        for process in processes:
            output, error = process.communicate(timeout=15)
            assert process.returncode == 0, error
            results.append(json.loads(output))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
    assert sum(value["result"] == "running" for value in results) == 1
    assert sum(value["result"] == "NOT_CLAIMABLE" for value in results) == 3
    assert store.status(OWNER, job_id)["job"]["attempts"] == 1
    assert [entry["event"] for entry in store.audit(OWNER, job_id)] == [
        "prepared",
        "queued",
        "claimed",
    ]

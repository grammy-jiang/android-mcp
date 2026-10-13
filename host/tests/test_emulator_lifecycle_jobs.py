"""H3.c synthetic emulator lifecycle; no real QEMU or Android device involved."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER, provider

from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.server import create_server

REQUEST = "synthetic-start-request"


def fake_emulator(
    path: Path,
    *,
    serial: str = "emulator-5554",
    qemu: bool = True,
    boot: bool = True,
    name: str = NAME,
    api: int = 36,
    abi: str = "arm64-v8a",
    delay: float = 0.0,
) -> tuple[Path, str]:
    executable = path / "mcp-fixture-emulator"
    report = {
        "qemu": qemu,
        "avd": name,
        "serial": serial,
        "api": api,
        "abi": abi,
        "boot_completed": boot,
    }
    script = (
        "#!/usr/bin/env python3\n"
        "# ANDROID-MCP-SYNTHETIC-EMULATOR-ONLY\n"
        "import json,os,sys,time,threading,signal\n"
        "def on_host_exit():\n"
        " sys.stdin.buffer.read()\n"
        " os._exit(0)\n"
        "threading.Thread(target=on_host_exit,daemon=True).start()\n"
        f"time.sleep({delay!r})\n"
        f"r=json.loads({json.dumps(report)!r})\n"
        "r['pid']=os.getpid()\n"
        "print(json.dumps(r),flush=True)\n"
        "while True: time.sleep(0.1)\n"
    )
    executable.write_text(script, encoding="utf-8")
    executable.chmod(0o700)
    return executable, hashlib.sha256(script.encode("utf-8")).hexdigest()


def engine(
    tmp_path: Path,
    *,
    backend: bool = True,
    readiness_timeout: float = 2.0,
    emulator_kwargs: dict[str, Any] | None = None,
) -> tuple[Any, Any, DurableJobStore, Any]:
    from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
    from android_mcp_host.synthetic_emulator_backend import SyntheticEmulatorBackend

    target = provider(tmp_path)
    created = target.provision("create", NAME)
    assert created["status"] == "created"
    ledger = DurableJobStore(tmp_path / "jobs", lease_seconds=90.0)
    launcher = None
    if backend:
        path, digest = fake_emulator(tmp_path, **(emulator_kwargs or {}))
        launcher = SyntheticEmulatorBackend(path, digest)
    controller = EmulatorLifecycle(
        target,
        ledger,
        owner=OWNER,
        backend=launcher,
        readiness_timeout_s=readiness_timeout,
    )
    return controller, created["avd"]["handle"], ledger, launcher


def test_t_h3c_01_owned_fixture_launch_verified_readiness_and_durable_receipt(
    tmp_path: Path,
) -> None:
    controller, handle, jobs, backend = engine(tmp_path)
    try:
        plan = controller.run("plan", NAME, handle)
        assert plan["status"] == "planned"
        assert plan["real_emulator_execution_enabled"] is False
        started = controller.run("start", NAME, handle, request_id=REQUEST)
        assert started["status"] == "ok" and started["lifecycle_state"] == "running"
        assert started["job_id"].startswith("job_")
        assert started["process_confirmed"] is True
        assert started["target"] == "disposable_emulator_only"
        assert jobs.status(OWNER, started["job_id"])["job"]["state"] == "running"
        status = controller.run("status", NAME, handle, job_id=started["job_id"])
        assert status["lifecycle_state"] == "running"
        assert status["process_confirmed"] is True
        assert str(tmp_path) not in json.dumps(status)
        stopped = controller.run("stop", NAME, handle, job_id=started["job_id"])
        assert stopped["lifecycle_state"] == "stopped"
        assert stopped["status"] == "ok"
        assert jobs.status(OWNER, started["job_id"])["job"]["state"] == "succeeded"
        assert [entry["event"] for entry in jobs.audit(OWNER, started["job_id"])] == [
            "prepared",
            "queued",
            "claimed",
            "succeeded",
        ]
    finally:
        controller.shutdown()


def test_t_h3c_02_foreign_avd_physical_target_and_disabled_default_denied(
    tmp_path: Path,
) -> None:
    controller, handle, jobs, _ = engine(tmp_path, backend=False)
    assert controller.run("start", NAME, handle, request_id=REQUEST)["status"] == "blocked"
    assert controller.run("plan", "android_mcp_native_api36", handle)["status"] == "blocked"
    assert (
        controller.run("start", NAME, "mcpavd_" + "x" * 32, request_id=REQUEST)["status"]
        == "blocked"
    )
    assert controller.run("plan", "-avd", handle)["status"] == "blocked"
    assert jobs.list_status(OWNER) == []
    assert controller.run("status", NAME, handle, job_id="job_" + "x" * 32)["status"] == "not_found"


def test_t_h3c_03_conflicting_double_start_hostile_request_and_no_reexecution(
    tmp_path: Path,
) -> None:
    controller, handle, jobs, _ = engine(tmp_path)
    try:
        first = controller.run("start", NAME, handle, request_id=REQUEST)
        second = controller.run("start", NAME, handle, request_id=REQUEST)
        assert second["job_id"] == first["job_id"]
        assert second["lifecycle_state"] == "running"
        other = controller.run("start", NAME, handle, request_id="different-request")
        assert other["status"] == "blocked"
        for request_id in ("", "-install", "../invalid", "x" * 200):
            assert (
                controller.run("start", NAME, handle, request_id=request_id)["status"] == "blocked"
            )
        assert len(jobs.list_status(OWNER)) == 1
        assert jobs.status(OWNER, first["job_id"])["job"]["attempts"] == 1
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "report",
    [
        {"serial": "USB-FEATURE-DEVICE"},
        {"serial": "emulator-5555"},
        {"api": 34},
        {"abi": "x86_64"},
        {"name": "another-owned-avd"},
        {"boot": False},
        {"qemu": False},
    ],
)
def test_t_h3c_04_readiness_mismatch_never_reports_booted(
    tmp_path: Path,
    report: dict[str, Any],
) -> None:
    controller, handle, jobs, _ = engine(tmp_path, emulator_kwargs=report)
    try:
        result = controller.run("start", NAME, handle, request_id=REQUEST)
        assert result["status"] in {"failed", "uncertain"}
        assert result["lifecycle_state"] != "running"
        assert result["process_confirmed"] is False
        assert result["job_id"] is not None
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] in {"failed", "uncertain"}
    finally:
        controller.shutdown()


def test_t_h3c_05_timeout_shutdown_restart_uncertain_and_no_replay(
    tmp_path: Path,
) -> None:
    from android_mcp_host.emulator_lifecycle import EmulatorLifecycle

    controller, handle, jobs, backend = engine(
        tmp_path, readiness_timeout=0.1, emulator_kwargs={"delay": 3.0}
    )
    timeout = controller.run("start", NAME, handle, request_id=REQUEST)
    assert timeout["status"] == "uncertain"
    assert timeout["process_confirmed"] is False
    controller.shutdown()
    assert jobs.status(OWNER, timeout["job_id"])["job"]["state"] == "uncertain"
    restarted = EmulatorLifecycle(
        controller.provisioner,
        DurableJobStore(tmp_path / "jobs", lease_seconds=90),
        owner=OWNER,
        backend=backend,
    )
    assert (
        restarted.run("status", NAME, handle, job_id=timeout["job_id"])["lifecycle_state"]
        == "uncertain"
    )
    assert restarted.run("start", NAME, handle, request_id=REQUEST)["status"] == "uncertain"
    assert (
        restarted.run("start", NAME, handle, request_id="unrelated-request")["status"] == "blocked"
    )
    restarted.shutdown()


def test_t_h3c_06_fastmcp_contract_durable_status_and_no_real_emulator(
    tmp_path: Path,
) -> None:
    from android_mcp_host.emulator_lifecycle import get_emulator_lifecycle_schema

    controller, handle, jobs, _ = engine(tmp_path, backend=False)

    async def verify() -> None:
        async with Client(create_server()) as baseline:
            old = {tool.name: tool for tool in await baseline.list_tools()}
        async with Client(create_server(emulator_lifecycle=controller)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {*old, "host_emulator_lifecycle"}
            assert all(tools[name] == old[name] for name in old)
            tool = tools["host_emulator_lifecycle"]
            assert tool.output_schema == get_emulator_lifecycle_schema()
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["destructiveHint"] is True
            assert hints["readOnlyHint"] is False
            result = await client.call_tool(
                "host_emulator_lifecycle",
                {"action": "plan", "name": NAME, "handle": handle},
            )
            assert not result.is_error
            data = result.structured_content
            Draft202012Validator(tool.output_schema).validate(data)
            assert data["status"] == "planned"
            assert data["real_emulator_execution_enabled"] is False
            assert str(tmp_path) not in json.dumps(data)
            blocked = await client.call_tool(
                "host_emulator_lifecycle",
                {
                    "action": "start",
                    "name": NAME,
                    "handle": handle,
                    "request_id": REQUEST,
                },
            )
            assert blocked.structured_content["status"] == "blocked"

    asyncio.run(verify())
    assert jobs.list_status(OWNER) == []

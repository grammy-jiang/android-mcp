"""E1: framework-owned unexpected-error masking; no physical ADB traffic."""

from __future__ import annotations

import asyncio
import json
import subprocess

from fastmcp import Client

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.cli import main
from android_mcp_host.command_runner import RunResult
from android_mcp_host.operations import OperationService
from android_mcp_host.probes import ProbeService
from android_mcp_host.server import create_server

CANARY = "SYNTHETIC_UNEXPECTED_EXCEPTION_PRIVATE_CANARY_85739"
DEVICE = "FAKE-001"


class FakeAdb:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def inspect(self) -> AdbReport:
        if self.fail:
            raise RuntimeError(f"synthetic unexpected error: {CANARY}")
        return AdbReport(True, "/never/execute/adb", "37", None, (Device(DEVICE, "device", {}),))


def test_unhandled_exception_is_masked_at_mcp_boundary() -> None:
    async def scenario() -> None:
        async with Client(create_server(adb=FakeAdb(fail=True))) as client:
            result = await client.call_tool("device_status", {}, raise_on_error=False)
            assert result.is_error is True
            assert CANARY not in str(result.content)
            assert CANARY not in str(result.structured_content)

    asyncio.run(scenario())


def test_expected_application_results_and_denials_remain_structured() -> None:
    calls: list[list[str]] = []

    def probe(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="Enforcing\n", stderr="")

    def command(argv: list[str], timeout: float, byte_limit: int) -> RunResult:
        calls.append(argv)
        return RunResult(0, "synthetic ok\n", "", False)

    adb = FakeAdb()
    server = create_server(
        adb=adb,  # type: ignore[arg-type]
        probes=ProbeService(adb, reader=probe),  # type: ignore[arg-type]
        operations=OperationService(adb, runner=command),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        async with Client(server) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == ["device_status", "adb_observe", "adb_develop"]
            status = await client.call_tool("device_status", {})
            assert status.is_error is False
            assert status.data["runtime"] == "host"
            seen = await client.call_tool(
                "adb_observe", {"device_id": DEVICE, "probes": ["selinux"]}
            )
            assert seen.is_error is False
            assert seen.data["status"] == "ok"
            denied = await client.call_tool(
                "adb_develop",
                {
                    "device_id": DEVICE,
                    "action": {
                        "type": "instrument_test",
                        "package": "com.example.tests",
                        "runner": "com.example.TestRunner",
                    },
                },
            )
            assert denied.is_error is False
            assert denied.data["status"] == "error"
            assert denied.data["errors"][0]["code"] == "MUTATION_DISABLED"
            assert len(calls) == 1
            assert calls[0][1:3] == ["-s", DEVICE]
            assert "install" not in calls[0] and "instrument" not in calls[0]

    asyncio.run(scenario())


def test_cli_doctor_remains_independent_of_mcp_server(monkeypatch, capsys) -> None:
    import android_mcp_host.cli as cli

    monkeypatch.setattr(cli, "AdbClient", FakeAdb)
    assert main(["doctor"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["runtime"] == "host"
    assert output["devices"][0]["device_id"] == DEVICE

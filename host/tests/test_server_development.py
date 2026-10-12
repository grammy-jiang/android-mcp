"""Actual FastMCP in-process test, to be run in a locked Host environment."""

import asyncio

from fastmcp import Client

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.command_runner import RunResult
from android_mcp_host.operations import OperationService
from android_mcp_host.server import create_server


class FakeAdb:
    def inspect(self):
        return AdbReport(True, "/fake/adb", "37", None, (Device("MOCK-01", "device", {}),))


def test_server_has_small_catalog_and_stays_read_only_by_default():
    async def test():
        adb = FakeAdb()
        operations = OperationService(
            adb, runner=lambda *args: RunResult(0, "android test", "", False)
        )
        server = create_server(adb=adb, operations=operations)
        async with Client(server) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == ["device_status", "adb_observe", "adb_develop"]
            reply = await client.call_tool(
                "adb_develop", {"device_id": "MOCK-01", "action": {"type": "logcat_snapshot"}}
            )
            assert not reply.is_error
            assert reply.data["status"] == "ok"
            mutation = await client.call_tool(
                "adb_develop",
                {
                    "device_id": "MOCK-01",
                    "action": {
                        "type": "instrument_test",
                        "package": "com.example.tests",
                        "runner": "androidx.test.runner.AndroidJUnitRunner",
                    },
                },
            )
            assert not mutation.is_error
            assert mutation.data["errors"][0]["code"] == "MUTATION_DISABLED"

    asyncio.run(test())

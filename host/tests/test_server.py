import asyncio

from fastmcp import Client

from android_mcp_host.adb import AdbClient
from android_mcp_host.server import create_server


def test_local_mcp_server_registers_only_readonly_status():
    async def exercise():
        server = create_server(AdbClient(locator=lambda _: None))
        async with Client(server) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == ["device_status"]
            result = await client.call_tool("device_status", {})
            assert not result.is_error
            assert result.data["schema_version"] == 1
            assert result.data["adb"]["error"]["code"] == "ADB_NOT_FOUND"

    asyncio.run(exercise())

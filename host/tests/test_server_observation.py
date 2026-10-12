"""FastMCP adapter smoke: service's real tool catalog stays small."""

import asyncio

from fastmcp import Client

from android_mcp_host.server import create_server


class FakeObservation:
    def __init__(self):
        self.calls = []

    def observe(self, device_id, probes):
        self.calls.append((device_id, probes))
        return {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id,
            "status": "ok",
            "results": [
                {"probe": "battery", "fields": {"battery": "level: 70"}, "truncated_fields": []}
            ],
            "errors": [],
        }


def test_registered_mcp_observer_uses_typed_backend():
    async def exercise():
        fake = FakeObservation()
        server = create_server(probes=fake)
        async with Client(server) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {"device_status", "adb_observe", "adb_develop"}
            response = await client.call_tool(
                "adb_observe", {"device_id": "SERIAL", "probes": ["battery"]}
            )
            assert response.is_error is False
            assert response.data["status"] == "ok"
            assert fake.calls == [("SERIAL", ["battery"])]

    asyncio.run(exercise())

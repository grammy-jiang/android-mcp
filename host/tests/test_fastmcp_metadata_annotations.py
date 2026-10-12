"""I3: metadata must conservatively represent Host effects and permissions."""

from __future__ import annotations

import asyncio

from fastmcp import Client

from android_mcp_host.server import create_server

EXPECTED = {
    "device_status": {
        "title": "Inspect Android Host and ADB",
        "readOnlyHint": False,  # discovery can start a host-side daemon
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "adb_observe": {
        "title": "Read Selected Android Device Diagnostics",
        "readOnlyHint": False,  # starting the host ADB daemon is a side effect
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "adb_develop": {
        "title": "Typed Android Engineering Diagnostics and Plans",
        "readOnlyHint": False,  # coordinator injection can enable mutation
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
}


def test_metadata_describes_real_read_write_permissions_and_is_stable():
    async def scenario():
        server = create_server()
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == set(EXPECTED)
            for name, fields in EXPECTED.items():
                tool = tools[name]
                assert tool.title == fields["title"]
                assert tool.annotations is not None
                hints = tool.annotations.model_dump(mode="json", by_alias=True)
                for field in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                    assert hints[field] is fields[field], (name, field, hints[field])
            assert {t.name: t.output_schema["$id"] for t in tools.values()} == {
                "device_status": "urn:android-mcp:device-status:v1",
                "adb_observe": "urn:android-mcp:adb-observation:v1",
                "adb_develop": "urn:android-mcp:adb-development:v1",
            }

    asyncio.run(scenario())


def test_server_instructions_disclose_discovery_effects_and_denied_mutation():
    server = create_server()
    instructions = server.instructions.lower()
    assert "adb daemon" in instructions
    assert "explicit" in instructions
    assert "mutation" in instructions
    assert "approval" in instructions
    assert "read-only" in instructions
    assert "all tools are read-only" not in instructions
    assert "tools are read-only" not in instructions

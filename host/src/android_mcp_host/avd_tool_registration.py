"""Small opt-in FastMCP adapter for the read-only Host AVD inventory."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from android_mcp_host.avd_inventory import AvdInventory, get_avd_output_schema


def register_avd_inventory_tool(server: FastMCP, provider: AvdInventory) -> None:
    """Register exactly one read-only Tool on an operator-selected Host."""

    @server.tool(
        title="Inspect Local Android Virtual Devices",
        output_schema=get_avd_output_schema(),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_avd_inventory(name: str | None = None) -> dict[str, object]:
        """Inspect operator-pinned local AVD metadata without changing emulator state.

        No AVD start/stop, physical USB target, arbitrary shell, or host paths.
        """
        return await asyncio.to_thread(provider.inspect, name)

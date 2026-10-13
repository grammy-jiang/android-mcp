"""Host-only opt-in FastMCP wrapper for fenced disposable AVD files."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.avd_provisioning import AvdProvisioner, get_avd_provision_schema


def register_avd_provision_tool(server: FastMCP, provider: AvdProvisioner) -> None:
    @server.tool(
        title="Manage Private Disposable Synthetic Android Virtual Device",
        output_schema=get_avd_provision_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_avd_provision(
        action: Literal["plan", "create", "delete"],
        name: str,
        handle: str | None = None,
    ) -> dict[str, object]:
        """Create/delete only signed MCP-owned private AVD metadata by opaque handle.

        Does not touch user-owned AVDs, start emulators, use ADB, download SDK
        images, accept licenses, or authorize physical device operations.
        """
        return await asyncio.to_thread(provider.provision, action, name, handle)

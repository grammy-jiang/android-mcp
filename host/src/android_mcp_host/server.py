"""FastMCP host server: read-only tools until policy design is completed."""

from __future__ import annotations

from fastmcp import FastMCP

from android_mcp_host.adb import AdbClient
from android_mcp_host.status import build_status


def create_server(adb: AdbClient | None = None) -> FastMCP:
    client = adb if adb is not None else AdbClient()
    server = FastMCP(
        "android-mcp-host",
        instructions=(
            "Android host device status is read-only. "
            "No APK, shell, root, UI actions, or remote control are implemented yet."
        ),
    )

    @server.tool
    def device_status() -> dict[str, object]:
        """Inspect host platform and ADB device states; never change a device."""
        return build_status(client)

    return server

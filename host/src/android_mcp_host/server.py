"""FastMCP host server: read-only tools until policy design is completed."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from android_mcp_host.adb import AdbClient
from android_mcp_host.operations import OperationService
from android_mcp_host.probes import ProbeService
from android_mcp_host.status import build_status


def create_server(
    adb: AdbClient | None = None,
    probes: ProbeService | None = None,
    operations: OperationService | None = None,
) -> FastMCP:
    client = adb if adb is not None else AdbClient()
    observer = probes if probes is not None else ProbeService(client)
    operator = operations if operations is not None else OperationService(client)
    server = FastMCP(
        "android-mcp-host",
        mask_error_details=True,
        instructions=(
            "Android host device tools are read-only. "
            "Each observation requires an explicitly selected authorized device. "
            "Typed Host actions only. Mutations remain disabled without independent "
            "trusted approval, device lease and audit configuration. "
            "No raw shell, root or remote network access is provided."
        ),
    )

    @server.tool
    def device_status() -> dict[str, object]:
        """Inspect host platform and ADB device states; never change a device."""
        return build_status(client)

    @server.tool
    async def adb_observe(device_id: str, probes: list[str]) -> dict[str, object]:
        """Read selected device diagnostics: identity, boot, battery, display,
        storage, selinux, shell_identity, third_party_packages, compatibility. Read-only.
        The serial must match one online, authorized device from device_status.
        """
        return await asyncio.to_thread(observer.observe, device_id, probes)

    @server.tool
    async def adb_develop(
        device_id: str, action: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]:
        """Perform typed read-only package/logcat diagnostics or preview
        APK installation and instrumentation. Mutations require trusted host
        approval, lease and audit gates, absent from this initial server.
        """
        return await asyncio.to_thread(operator.execute, device_id, action, dry_run=dry_run)

    return server

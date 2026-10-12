"""FastMCP host server: read-only tools until policy design is completed."""

from __future__ import annotations

import asyncio
import threading
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from android_mcp_host.adb import AdbClient
from android_mcp_host.adb_transport import AdbTransport, get_transport_output_schema
from android_mcp_host.capability_profiles import CapabilityProfiles, get_capability_output_schema
from android_mcp_host.device_discovery import DeviceDiscovery, get_device_list_output_schema
from android_mcp_host.mcp_boundary import get_development_action_field_schema, get_output_schema
from android_mcp_host.operations import OperationService
from android_mcp_host.probes import MAX_PROBES, PROBES, ProbeService
from android_mcp_host.status import build_status
from android_mcp_host.toolchain_inventory import (
    ToolchainInventory,
    get_toolchain_output_schema,
)


def create_server(
    adb: AdbClient | None = None,
    probes: ProbeService | None = None,
    operations: OperationService | None = None,
    toolchain_inventory: ToolchainInventory | None = None,
    capability_profiles: CapabilityProfiles | None = None,
    adb_discovery: DeviceDiscovery | None = None,
    adb_transport: AdbTransport | None = None,
) -> FastMCP:
    client = adb if adb is not None else AdbClient()
    observer = probes if probes is not None else ProbeService(client)
    operator = operations if operations is not None else OperationService(client)
    server = FastMCP(
        "android-mcp-host",
        mask_error_details=True,
        instructions=(
            "Android Host tools provide read-only device diagnostics and bounded plans. "
            "ADB discovery may start the local ADB daemon, so host state can change. "
            "Every device operation requires an explicit online authorized device. "
            "Typed engineering actions can describe mutation, but actual mutation "
            "is denied without independent trusted approval, device lease and audit. "
            "No raw shell, root or remote network access is provided."
        ),
    )

    @server.tool(
        title="Inspect Android Host and ADB",
        output_schema=get_output_schema("device_status"),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def device_status() -> dict[str, object]:
        """Inspect host platform and ADB device states; never change a device."""
        return build_status(client)

    @server.tool(
        title="Read Selected Android Device Diagnostics",
        output_schema=get_output_schema("adb_observe"),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adb_observe(
        device_id: str,
        probes: Annotated[
            list[str],
            Field(
                description="Select 1-8 distinct allowlisted ADB observation groups.",
                json_schema_extra={
                    "minItems": 1,
                    "maxItems": MAX_PROBES,
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": sorted(PROBES)},
                },
            ),
        ],
    ) -> dict[str, object]:
        """Read selected device diagnostics: identity, boot, battery, display,
        storage, selinux, shell_identity, third_party_packages, compatibility. Read-only.
        The serial must match one online, authorized device from device_status.
        """
        return await asyncio.to_thread(observer.observe, device_id, probes)

    @server.tool(
        title="Typed Android Engineering Diagnostics and Plans",
        output_schema=get_output_schema("adb_develop"),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adb_develop(
        device_id: str,
        action: Annotated[
            dict[str, object],
            Field(
                description="One of four typed, allowlisted Android engineering actions.",
                json_schema_extra=get_development_action_field_schema(),
            ),
        ],
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Perform typed, bounded package/logcat diagnostics and action planning.

        Instrumentation can be previewed without changing the device. APK
        installation is refused unless trusted Host directories are configured.
        Execution of mutation additionally requires independent operator
        approval, device lease and durable audit; default Host disables it.
        """
        return await asyncio.to_thread(operator.execute, device_id, action, dry_run=dry_run)

    if toolchain_inventory is not None:

        @server.tool(
            title="Inspect Fixed Android Host Toolchain",
            output_schema=get_toolchain_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        def host_toolchain_inventory() -> dict[str, object]:
            """Inspect trusted fixed-path CLI versions and SDK; never install or update."""
            return toolchain_inventory.inspect()

    if capability_profiles is not None:

        @server.tool(
            title="Inspect Approved Host Capability Profile",
            output_schema=get_capability_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        def host_capability_profile() -> dict[str, object]:
            """Report bounded Host capability states; never grant mutation or leases."""
            return capability_profiles.snapshot()

    if adb_discovery is not None:

        @server.tool(
            title="List Read-Only ADB Device Targets",
            output_schema=get_device_list_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        def adb_devices_list() -> dict[str, object]:
            """List ADB device states and transport IDs; never connect or select a device."""
            return adb_discovery.list_devices()

    if adb_transport is not None:

        @server.tool(
            title="Inspect Exact Android ADB Transport",
            output_schema=get_transport_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def adb_transport_inspect(
            device_id: str,
            transport_id: str,
            target_state: str = "device",
            wait_seconds: float = 0.0,
            include_routes: bool = False,
            include_mdns: bool = False,
            mdns_endpoint: str | None = None,
        ) -> dict[str, object]:
            """Inspect an exact serial + transport ID, with bounded state wait.

            Optionally list only TCP port numbers and count valid mDNS services.
            No pairing, connect/disconnect, forwarding setup, or raw address
            disclosure. This Tool does not authorize subsequent device actions.
            """
            cancel = threading.Event()
            try:
                return await asyncio.to_thread(
                    adb_transport.inspect,
                    device_id=device_id,
                    transport_id=transport_id,
                    target_state=target_state,
                    wait_seconds=wait_seconds,
                    include_routes=include_routes,
                    include_mdns=include_mdns,
                    mdns_endpoint=mdns_endpoint,
                    cancel=cancel,
                )
            except asyncio.CancelledError:
                cancel.set()
                raise

    return server

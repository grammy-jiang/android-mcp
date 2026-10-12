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
from android_mcp_host.fastboot_inventory import FastbootInventory, get_fastboot_output_schema
from android_mcp_host.logcat_filters import LogcatFilters, get_logcat_output_schema
from android_mcp_host.mcp_boundary import get_development_action_field_schema, get_output_schema
from android_mcp_host.operations import OperationService
from android_mcp_host.package_inspector import (
    MAX_PERMISSIONS,
    PackageInspector,
    get_package_output_schema,
)
from android_mcp_host.probes import MAX_PROBES, PROBES, ProbeService
from android_mcp_host.sdk_ndk_inventory import SdkNdkInventory, get_sdk_ndk_output_schema
from android_mcp_host.status import build_status
from android_mcp_host.system_snapshot import SystemSnapshot, get_snapshot_output_schema
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
    system_snapshot: SystemSnapshot | None = None,
    package_inspector: PackageInspector | None = None,
    logcat_filter: LogcatFilters | None = None,
    fastboot_inventory: FastbootInventory | None = None,
    sdk_ndk_inventory: SdkNdkInventory | None = None,
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

    if system_snapshot is not None:

        @server.tool(
            title="Read Typed Android System Snapshot",
            output_schema=get_snapshot_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def adb_system_snapshot(device_id: str, groups: list[str]) -> dict[str, object]:
            """Read fixed device-pinned identity, battery, storage, display and network fields.

            No arbitrary dumpsys or shell input. Invalid and unavailable fields
            remain explicitly partial or denied; never enable device mutation.
            """
            return await asyncio.to_thread(system_snapshot.inspect, device_id, groups)

    if package_inspector is not None:

        @server.tool(
            title="Inspect Exact Android Package Metadata",
            output_schema=get_package_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def adb_package_inspect(
            device_id: str,
            package: str,
            include_permissions: bool = True,
            permission_limit: int = MAX_PERMISSIONS,
        ) -> dict[str, object]:
            """Read one exact package version/SDK and bounded permission summary.

            No installation, uninstall, arbitrary command or raw dumpsys output.
            """
            return await asyncio.to_thread(
                package_inspector.inspect,
                device_id,
                package,
                include_permissions=include_permissions,
                permission_limit=permission_limit,
            )

    if logcat_filter is not None:

        @server.tool(
            title="Capture Bounded Redacted Android Logcat",
            output_schema=get_logcat_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def adb_logcat_filter(
            device_id: str,
            lines: int = 100,
            tag: str | None = None,
            package: str | None = None,
            severity: str | None = None,
            timeout_s: float = 5.0,
        ) -> dict[str, object]:
            """Inspect device-pinned, bounded Logcat messages with best-effort redaction.

            Logs can contain sensitive personal or application data. Never use
            this Tool for unconsented collection; no arbitrary shell, file
            capture, unbounded streaming or device modification is supported.
            """
            return await asyncio.to_thread(
                logcat_filter.capture,
                device_id,
                lines=lines,
                tag=tag,
                package=package,
                severity=severity,
                timeout_s=timeout_s,
            )

    if fastboot_inventory is not None:

        @server.tool(
            title="Discover Read-Only Fastboot Transports",
            output_schema=get_fastboot_output_schema(),
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def fastboot_devices_list() -> dict[str, object]:
            """Read fixed Fastboot version and device transport listing only.

            No getvar, flash, unlock, erase, reboot, recovery state change,
            mode switch, ADB fallback or inferred device authorization.
            """
            return await asyncio.to_thread(fastboot_inventory.discover)

    if sdk_ndk_inventory is not None:

        @server.tool(
            title="Inspect Fixed Android Host SDK/NDK Workstation",
            output_schema=get_sdk_ndk_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def host_sdk_ndk_inventory() -> dict[str, object]:
            """Inspect fixed local SDK/JDK/NDK/Gradle prerequisites only.

            No SDK installation, update, license agreement acceptance,
            Gradle task execution, Android device operation or build grant.
            Availability is not authorization or proof of accepted licenses.
            """
            return await asyncio.to_thread(sdk_ndk_inventory.inspect)

    return server

"""FastMCP host server: read-only tools until policy design is completed."""

from __future__ import annotations

import asyncio
import threading
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from android_mcp_host.adb import AdbClient
from android_mcp_host.adb_transport import AdbTransport, get_transport_output_schema
from android_mcp_host.android_build_preflight import (
    AndroidBuildPreflight,
    get_build_preflight_output_schema,
)
from android_mcp_host.archive_inspector import ArchiveInspector, get_archive_output_schema
from android_mcp_host.capability_profiles import CapabilityProfiles, get_capability_output_schema
from android_mcp_host.controlled_build_jobs import ControlledBuildJobs, get_build_job_schema
from android_mcp_host.device_discovery import DeviceDiscovery, get_device_list_output_schema
from android_mcp_host.durable_jobs import DurableJobStore, get_job_status_schema
from android_mcp_host.fastboot_inventory import FastbootInventory, get_fastboot_output_schema
from android_mcp_host.logcat_filters import LogcatFilters, get_logcat_output_schema
from android_mcp_host.mcp_boundary import get_development_action_field_schema, get_output_schema
from android_mcp_host.operations import OperationService
from android_mcp_host.package_inspector import (
    MAX_PERMISSIONS,
    PackageInspector,
    get_package_output_schema,
)
from android_mcp_host.private_artifact_store import (
    PrivateArtifactStore,
    get_artifact_metadata_schema,
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
    build_preflight: AndroidBuildPreflight | None = None,
    artifact_store: PrivateArtifactStore | None = None,
    artifact_owner: str | None = None,
    archive_inspector: ArchiveInspector | None = None,
    build_jobs: ControlledBuildJobs | None = None,
    durable_jobs: DurableJobStore | None = None,
    job_owner: str | None = None,
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

    if build_preflight is not None:

        @server.tool(
            title="Preview Approved Android Build Preflight",
            output_schema=get_build_preflight_output_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def android_build_preflight(
            action: Literal["assemble_debug", "lint_debug", "test_jvm"] = "assemble_debug",
            variant: Literal["debug"] = "debug",
        ) -> dict[str, object]:
            """Preview a fixed Gradle task plan for an operator-pinned project.

            No Gradle wrapper or build command is executed. This does not
            authorize a build, accept SDK licenses or trust an unsigned input.
            Only Host operator config can supply root and approved SHA pins.
            """
            return await asyncio.to_thread(build_preflight.plan, action, variant)

    if (artifact_store is None) != (artifact_owner is None):
        raise ValueError("Artifact metadata needs a trusted store and owner")
    if artifact_store is not None and artifact_owner is not None:
        if not artifact_store.validate_owner(artifact_owner):
            raise ValueError("Invalid Host artifact owner")

        @server.tool(
            title="Inspect Private Artifact Metadata",
            output_schema=get_artifact_metadata_schema(),
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def host_artifact_metadata(handle: str) -> dict[str, object]:
            """Get opaque owner-scoped metadata; never read or return raw content.

            Ownership is bound to this trusted Host service, not chosen by a
            remote MCP client. No download, upload, install or signing action.
            """
            return await asyncio.to_thread(artifact_store.public_metadata, artifact_owner, handle)

    if archive_inspector is not None:

        @server.tool(
            title="Inspect Private APK or AAB Archive",
            output_schema=get_archive_output_schema(),
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def host_archive_inspect(handle: str) -> dict[str, object]:
            """Inspect only operator-scoped private APK/AAB metadata by opaque handle.

            Read-only ZIP inspection; a cryptographic signature is reported
            verified only when a preconfigured trusted vendor verifier succeeds.
            The caller cannot select paths, owner, binaries, commands or devices.
            """
            return await asyncio.to_thread(archive_inspector.inspect, handle)

    if build_jobs is not None:

        @server.tool(
            title="Run Operator-Approved Offline Gradle Job",
            output_schema=get_build_job_schema(),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def host_gradle_build(
            action: Literal["assemble_debug", "lint_debug", "test_jvm"],
            request_id: str,
        ) -> dict[str, object]:
            """Run only a preapproved finite offline Gradle action by idempotency key.

            Does not authorize installs, USB access or physical-device mutation.
            Operator pins source commit, wrapper digest, roots and owner context.
            """
            return await asyncio.to_thread(build_jobs.submit, action, request_id)

    if (durable_jobs is None) != (job_owner is None):
        raise ValueError("Durable job status needs a trusted store and owner")
    if durable_jobs is not None and job_owner is not None:
        if not durable_jobs.validate_owner(job_owner):
            raise ValueError("Invalid Host job owner")

        @server.tool(
            title="Inspect Durable Host Job Status",
            output_schema=get_job_status_schema(),
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def host_job_status(job_id: str) -> dict[str, object]:
            """Read only a trusted owner's opaque persistent job state.

            Never authorizes a job, dispatches a worker, retries uncertain
            effects, changes device state or returns owner/secrets.
            """
            return await asyncio.to_thread(durable_jobs.status, job_owner, job_id)

    return server

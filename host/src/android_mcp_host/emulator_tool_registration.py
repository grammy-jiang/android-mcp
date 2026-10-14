"""Host emulator development Tool registry, preserving legacy tool ordering."""

from __future__ import annotations

from fastmcp import FastMCP

from android_mcp_host.avd_inventory import AvdInventory
from android_mcp_host.avd_provision_tool import register_avd_provision_tool
from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.avd_tool_registration import register_avd_inventory_tool
from android_mcp_host.emulator_debug_deployment import DebugDeployment
from android_mcp_host.emulator_debug_tool import register_debug_deployment_tool
from android_mcp_host.emulator_instrumentation_jobs import InstrumentationJobs
from android_mcp_host.emulator_instrumentation_tool import register_instrumentation_tool
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.emulator_lifecycle_tool import register_emulator_lifecycle_tool


def register_emulator_tools(
    server: FastMCP,
    inventory: AvdInventory | None,
    provisioner: AvdProvisioner | None,
    lifecycle: EmulatorLifecycle | None,
    instrumentation: InstrumentationJobs | None,
    deployment: DebugDeployment | None,
) -> None:
    if inventory is not None:
        register_avd_inventory_tool(server, inventory)
    if provisioner is not None:
        register_avd_provision_tool(server, provisioner)
    if lifecycle is not None:
        register_emulator_lifecycle_tool(server, lifecycle)
    if instrumentation is not None:
        register_instrumentation_tool(server, instrumentation)
    if deployment is not None:
        register_debug_deployment_tool(server, deployment)

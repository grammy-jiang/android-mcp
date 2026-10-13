"""Opt-in FastMCP adapter for inert, private synthetic debug deployment."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.emulator_debug_deployment import (
    DebugDeployment,
    get_debug_deploy_schema,
)


def register_debug_deployment_tool(server: FastMCP, worker: DebugDeployment) -> None:
    @server.tool(
        title="Plan Synthetic-Owned Debug APK Deployment",
        output_schema=get_debug_deploy_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_emulator_debug_deploy(
        action: Literal["plan", "install", "launch", "uninstall", "cleanup", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        package_id: str,
        request_id: str | None = None,
        install_report_handle: str | None = None,
        job_id: str | None = None,
        original_action: Literal["install", "launch", "uninstall", "cleanup"] | None = None,
    ) -> dict[str, object]:
        """Synthetic fixture only; never calls real ADB install or launches Android apps."""
        return await asyncio.to_thread(
            worker.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            apk_handle,
            apk_sha256,
            package_id,
            request_id=request_id,
            install_report_handle=install_report_handle,
            job_id=job_id,
            original_action=original_action,
        )

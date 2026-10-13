"""Opt-in FastMCP interface to private synthetic snapshot metadata only."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.emulator_snapshot_manager import (
    EmulatorSnapshotManager,
    get_snapshot_output_schema,
)


def register_snapshot_tool(server: FastMCP, manager: EmulatorSnapshotManager) -> None:
    @server.tool(
        title="Manage Private Synthetic Emulator Snapshot Records",
        output_schema=get_snapshot_output_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_emulator_snapshot(
        action: Literal["create", "list", "restore", "delete", "fault_plan", "cancel"],
        avd_name: str,
        avd_handle: str,
        snapshot_name: str | None = None,
        snapshot_handle: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        condition: Literal["boot_delay", "network_disconnect", "process_crash"] | None = None,
    ) -> dict[str, object]:
        """Manipulate only signed synthetic records; no real emulator snapshot I/O."""
        return await asyncio.to_thread(
            manager.operate,
            action,
            avd_name,
            avd_handle,
            snapshot_name,
            snapshot_handle=snapshot_handle,
            request_id=request_id,
            job_id=job_id,
            condition=condition,
        )

"""FastMCP adapter for privacy-filtered synthetic UI hierarchy inspection."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_ui_hierarchy import UiHierarchyService, get_ui_hierarchy_schema


def register_ui_hierarchy_tool(server: FastMCP, reader: UiHierarchyService) -> None:
    @server.tool(
        title="Plan Bounded Redacted Synthetic UI Hierarchy Inspection",
        output_schema=get_ui_hierarchy_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def host_ui_hierarchy(
        action: Literal["plan", "inspect"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        request_id: str | None = None,
    ) -> dict[str, object]:
        """No Accessibility bypass, raw XML, real ADB read or UI input action.
        A trusted synthetic UI approval and fixture runner are required to
        return redacted nodes; the normal Host CLI provides plans only.
        """
        return await asyncio.to_thread(
            reader.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            request_id=request_id,
        )

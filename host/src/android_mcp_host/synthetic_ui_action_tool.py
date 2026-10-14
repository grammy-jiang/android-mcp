"""Bounded synthetic-only UI tap/swipe/key MCP Tool; real input disabled."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_ui_actions import UiActionService, get_ui_action_schema


def register_ui_action_tool(server: FastMCP, worker: UiActionService) -> None:
    @server.tool(
        title="Plan a Scoped Synthetic Emulator UI Action",
        output_schema=get_ui_action_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_ui_action(
        operation: Literal["plan", "execute", "cancel"],
        kind: Literal["tap", "swipe", "key"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        window_id: str,
        window_generation: int,
        rotation: int,
        focused_node_id: str,
        x: int | None = None,
        y: int | None = None,
        x2: int | None = None,
        y2: int | None = None,
        duration_ms: int | None = None,
        keycode: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Sensitive synthetic-only UI mutation; real ADB input stays disabled.

        Only fixed fake tap, swipe, and allowlisted keycode operations are
        compiled. No arbitrary adb shell, physical device writes, input
        text, Accessibility permission bypass, or default executor exists.
        A trusted expiring grant and exact window witness are required.
        """
        return await asyncio.to_thread(
            worker.submit,
            operation,
            kind,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            window_id,
            window_generation,
            rotation,
            focused_node_id,
            x=x,
            y=y,
            x2=x2,
            y2=y2,
            duration_ms=duration_ms,
            keycode=keycode,
            request_id=request_id,
            job_id=job_id,
        )

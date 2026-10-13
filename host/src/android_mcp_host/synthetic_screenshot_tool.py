"""Sensitive synthetic screenshot Tool, deliberately disabled for real ADB capture."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_screenshot import ScreenshotArtifacts, get_screenshot_schema


def register_screenshot_tool(server: FastMCP, worker: ScreenshotArtifacts) -> None:
    @server.tool(
        title="Plan Private Synthetic Screenshot Capture",
        output_schema=get_screenshot_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_screenshot(
        action: Literal["plan", "capture"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        request_id: str | None = None,
    ) -> dict[str, object]:
        """Capture is sensitive. Real ADB/device capture is disabled; only a
        trusted out-of-band synthetic approval and test fixture may enable it.
        Bytes never appear in Tool responses, logs or argument schemas.
        """
        return await asyncio.to_thread(
            worker.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            request_id=request_id,
        )

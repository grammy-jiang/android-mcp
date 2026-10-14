"""FastMCP contract: sensitive fake-only screenrecord, plan-only by default."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_screenrecord import ScreenRecordService, get_screenrecord_schema


def register_screenrecord_tool(server: FastMCP, recorder: ScreenRecordService) -> None:
    @server.tool(
        title="Plan Bounded Private Synthetic Video Recording",
        output_schema=get_screenrecord_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_screenrecord(
        action: Literal["plan", "record", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        duration_s: int = 5,
        display_id: int = 0,
        codec: Literal["h264"] = "h264",
        max_bytes: int = 262144,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Sensitive, bounded, private synthetic media: never returns video bytes.

        Real ADB screenrecord/physical capture is disabled. Production offers
        planning only; a test-owned fixture and independent expiring approval
        are required for recording and cancellation. No raw shell, paths or
        user-device media access are exposed.
        """
        return await asyncio.to_thread(
            recorder.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            duration_s=duration_s,
            display_id=display_id,
            codec=codec,
            max_bytes=max_bytes,
            request_id=request_id,
            job_id=job_id,
        )

"""FastMCP H5.c contract: private synthetic Perfetto plans and opaque trace receipts."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_perfetto import PerfettoService, get_perfetto_schema


def register_perfetto_tool(server: FastMCP, worker: PerfettoService) -> None:
    @server.tool(
        title="Plan Private Bounded Synthetic Perfetto Trace",
        output_schema=get_perfetto_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_perfetto_trace(
        action: Literal["plan", "capture", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        profile: Literal["sched-lite-v1", "frames-lite-v1"] = "sched-lite-v1",
        duration_s: int = 3,
        max_bytes: int = 131072,
        ttl_s: int = 60,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """No real Perfetto or ADB processes, root, paths or physical devices.

        Production can plan only. Successful capture requires a trusted
        test-owned AVD plus independent temporary debug/trace approval;
        the result returns metadata/handles, never raw trace bytes.
        """
        return await asyncio.to_thread(
            worker.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            profile=profile,
            duration_s=duration_s,
            max_bytes=max_bytes,
            ttl_s=ttl_s,
            request_id=request_id,
            job_id=job_id,
        )

"""H5.b sensitive finite synthetic Logcat Streamable HTTP/MCP adapter."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_logcat_stream import SyntheticLogcatStream, get_logcat_stream_schema


def register_logcat_stream_tool(server: FastMCP, worker: SyntheticLogcatStream) -> None:
    @server.tool(
        title="Plan Private Finite Synthetic Logcat Stream",
        output_schema=get_logcat_stream_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def host_logcat_stream(
        action: Literal["plan", "start", "poll", "stop"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        request_id: str | None = None,
        job_id: str | None = None,
        cursor: str | None = None,
        tag: Literal["McpTest", "ActivityManager", "System"] | None = None,
        max_events: int = 128,
        page_size: int = 8,
        ttl_s: int = 60,
    ) -> dict[str, object]:
        """One bounded fake-only capture, single-use cursor pages and stop.

        Real Android logcat, shell, arbitrary filters and physical devices
        remain disabled. Only an independently approved trusted test fixture
        can capture. Every poll is pinned to original lifecycle/request.
        """
        return await asyncio.to_thread(
            worker.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            request_id=request_id,
            job_id=job_id,
            cursor=cursor,
            tag=tag,
            max_events=max_events,
            page_size=page_size,
            ttl_s=ttl_s,
        )

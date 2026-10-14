"""Sensitive H5.a synthetic-only bugreport MCP Tool, real ADB disabled."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_bugreport import BugreportService, get_bugreport_schema


def register_bugreport_tool(server: FastMCP, collector: BugreportService) -> None:
    @server.tool(
        title="Plan Private Sanitized Synthetic Bugreport",
        output_schema=get_bugreport_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_bugreport(
        action: Literal["plan", "collect", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Sensitive synthetic-only diagnostics, no raw Android bugreport or shell.

        Production is plan-only: no ADB bugreport runner or physical-device
        read is supplied. Trusted test fixtures require an exact owner-pinned
        disposable AVD lifecycle and separate expiring private approval.
        Returned ZIP bytes are sanitized before private storage and never
        exposed as Tool JSON.
        """
        return await asyncio.to_thread(
            collector.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            request_id=request_id,
            job_id=job_id,
        )

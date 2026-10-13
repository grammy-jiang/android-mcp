"""Standalone registration for the existing owner-scoped H2.d job status Tool."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from android_mcp_host.durable_jobs import DurableJobStore, get_job_status_schema


def register_job_status_tool(server: FastMCP, store: DurableJobStore, owner: str) -> None:
    @server.tool(
        title="Inspect Durable Host Job Status",
        output_schema=get_job_status_schema(),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_job_status(job_id: str) -> dict[str, object]:
        """Read private job metadata, never dispatch, retry or authorize work."""
        return await asyncio.to_thread(store.status, owner, job_id)

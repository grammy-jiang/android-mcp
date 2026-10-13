"""Opt-in synthetic-only instrumentation Tool adapter for FastMCP."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.emulator_instrumentation_jobs import (
    InstrumentationJobs,
    get_instrumentation_schema,
)


def register_instrumentation_tool(server: FastMCP, worker: InstrumentationJobs) -> None:
    @server.tool(
        title="Plan or Simulate Owned Emulator Instrumentation Tests",
        output_schema=get_instrumentation_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_emulator_instrumentation(
        action: Literal["plan", "run", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        apk_handle: str,
        apk_sha256: str,
        component: str,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Only fixed synthetic test jobs; real ADB instrumentation disabled."""
        return await asyncio.to_thread(
            worker.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            apk_handle,
            apk_sha256,
            component,
            request_id=request_id,
            job_id=job_id,
        )

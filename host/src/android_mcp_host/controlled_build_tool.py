"""Existing H2.f bounded Gradle Tool registration, separate from server wiring."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.controlled_build_jobs import ControlledBuildJobs, get_build_job_schema


def register_build_tool(server: FastMCP, build_jobs: ControlledBuildJobs) -> None:
    @server.tool(
        title="Run Operator-Approved Offline Gradle Job",
        output_schema=get_build_job_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def host_gradle_build(
        action: Literal["assemble_debug", "lint_debug", "test_jvm"],
        request_id: str,
    ) -> dict[str, object]:
        """Run a finite approved offline Gradle action; never mutate devices."""
        return await asyncio.to_thread(build_jobs.submit, action, request_id)

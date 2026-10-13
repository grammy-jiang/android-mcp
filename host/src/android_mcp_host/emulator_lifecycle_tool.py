"""Small FastMCP registration adapter for synthetic-only H3.c lifecycle."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.emulator_lifecycle import (
    EmulatorLifecycle,
    get_emulator_lifecycle_schema,
)


def register_emulator_lifecycle_tool(server: FastMCP, provider: EmulatorLifecycle) -> None:
    """Register one explicit opt-in fake-only lifecycle Tool."""

    @server.tool(
        title="Plan and Inspect Synthetic Emulator Lifecycle",
        output_schema=get_emulator_lifecycle_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_emulator_lifecycle(
        action: Literal["plan", "start", "stop", "status"],
        name: str,
        handle: str,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """A typed synthetic-only state transition; no real QEMU device operations.

        Real emulator execution is always disabled in production composition.
        """
        return await asyncio.to_thread(
            provider.run, action, name, handle, request_id=request_id, job_id=job_id
        )

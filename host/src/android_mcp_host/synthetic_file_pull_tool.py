"""Host H4.d FastMCP private file export: default-denied real ADB read."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_file_pull import FilePullService, get_file_pull_schema


def register_file_pull_tool(server: FastMCP, exporter: FilePullService) -> None:
    @server.tool(
        title="Plan Private Synthetic App File Export",
        output_schema=get_file_pull_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_file_pull(
        action: Literal["plan", "pull", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        remote_path: str,
        expected_sha256: str | None = None,
        mime_type: Literal["application/json", "text/plain", "application/octet-stream"] = (
            "application/octet-stream"
        ),
        max_bytes: int = 262144,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Sensitive exact app-owned synthetic export to a private artifact handle.

        No real ADB, physical device, arbitrary /data read, symlink traversal,
        host output path, raw bytes, shell or filesystem write is exposed.
        Production is plan-only. Fixture execution requires an independent
        expiring operator-pinned source approval and verified disposable AVD.
        """
        return await asyncio.to_thread(
            exporter.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            remote_path,
            expected_sha256=expected_sha256,
            mime_type=mime_type,
            max_bytes=max_bytes,
            request_id=request_id,
            job_id=job_id,
        )

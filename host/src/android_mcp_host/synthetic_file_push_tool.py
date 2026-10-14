"""H4.e sensitive private test-only file import FastMCP Tool."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from android_mcp_host.synthetic_file_push import FilePushService, get_file_push_schema


def register_file_push_tool(server: FastMCP, importer: FilePushService) -> None:
    @server.tool(
        title="Plan Safe Private Synthetic App File Import",
        output_schema=get_file_push_schema(),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def host_file_push(
        action: Literal["plan", "push", "cancel"],
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        artifact_handle: str,
        artifact_sha256: str,
        destination_path: str,
        mime_type: Literal["application/octet-stream", "application/json", "text/plain"] = (
            "application/octet-stream"
        ),
        max_bytes: int = 262144,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Sensitive synthetic-only file mutation with no real ADB or physical writes.

        This Tool is plan-only in normal Host CLI configuration. A test HMAC
        attestation is never an Android signature or a real-device grant.
        Neither arbitrary output paths nor shell commands are available.
        """
        return await asyncio.to_thread(
            importer.submit,
            action,
            avd_name,
            avd_handle,
            lifecycle_job_id,
            artifact_handle,
            artifact_sha256,
            destination_path,
            mime_type=mime_type,
            max_bytes=max_bytes,
            request_id=request_id,
            job_id=job_id,
        )

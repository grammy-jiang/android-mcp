#!/usr/bin/env python3
"""Cross-language localhost MCP smoke for the JVM-only Kotlin prototype.

Starts a short-lived unprivileged Kotlin process, validates its synthetic
device_status against the shared Host/Native JSON Schema, then stops it.
No Android device, ADB, Root, network tunnel or credentials are required.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path

from fastmcp import Client
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN = (
    REPO_ROOT / "android/native-mcp-jvm/build/install/native-mcp-jvm/bin/native-mcp-jvm"
)
SCHEMA = REPO_ROOT / "contracts/device-status.v1.schema.json"


async def exercise(port: int) -> dict[str, object]:
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(80):
        try:
            async with Client(url) as client:
                tools = await client.list_tools()
                if [tool.name for tool in tools] != ["device_status"]:
                    raise AssertionError("JVM prototype tool catalog drifted")
                response = await client.call_tool("device_status", {})
                if response.is_error or len(response.content) != 1:
                    raise AssertionError("JVM prototype returned a tool failure")
                content = getattr(response.content[0], "text", None)
                if not isinstance(content, str) or len(content) > 128 * 1024:
                    raise AssertionError(
                        "JVM prototype status response is not bounded text"
                    )
                payload = json.loads(content)
                schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
                Draft202012Validator(schema).validate(payload)
                if (
                    payload["runtime"] != "android"
                    or payload["devices"]
                    or not payload["capabilities"]
                    or any(payload["capabilities"].values())
                    or payload["errors"]
                ):
                    raise AssertionError(
                        "JVM prototype must expose only synthetic safe status"
                    )
                return {
                    "result": "pass",
                    "language_boundary": "Python FastMCP -> Kotlin MCP SDK",
                    "transport": "loopback_http",
                    "synthetic_only": True,
                    "registered_tools": 1,
                    "schema_version": 1,
                }
        except (OSError, ConnectionError, RuntimeError):
            await asyncio.sleep(0.15)
    raise RuntimeError("Kotlin JVM loopback MCP listener failed to start")


def main() -> int:
    if not BIN.is_file() or not os.access(BIN, os.X_OK):
        raise RuntimeError(
            "Run Gradle :native-mcp-jvm:installDist before the wire smoke"
        )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    process = subprocess.Popen(
        [str(BIN), str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        report = asyncio.run(asyncio.wait_for(exercise(port), timeout=30))
        print(json.dumps(report, sort_keys=True))
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())

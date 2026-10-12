#!/usr/bin/env python3
"""Opt-in read-only HTTP MCP test against one explicitly authorized Android device.

Never implicitly selects a device or prints device output. Optional Logcat
is requested only with --logcat-lines. Not part of automatic CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
from typing import Any

from android_mcp_host.device_guard import valid_device_id
from android_mcp_host.probes import MAX_PROBES, PROBES
from fastmcp import Client

TOOL_NAMES = ["device_status", "adb_observe", "adb_develop"]
DEFAULT_PROBES = [
    "identity",
    "compatibility",
    "boot",
    "battery",
    "display",
    "storage",
    "selinux",
    "shell_identity",
]


def _ephemeral_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _body(reply: Any) -> dict[str, Any]:
    if reply.is_error or not isinstance(reply.data, dict):
        raise RuntimeError("Malformed or failed MCP tool result")
    return reply.data


async def _exercise(port: int, serial: str, probes: list[str], log_lines: int | None):
    url = f"http://127.0.0.1:{port}/mcp/"
    for _ in range(40):
        try:
            async with Client(url) as client:
                catalog = [tool.name for tool in await client.list_tools()]
                break
        except (OSError, ConnectionError):
            await asyncio.sleep(0.15)
    else:
        raise RuntimeError("Local MCP server did not become ready")

    async with Client(url) as client:
        if catalog != TOOL_NAMES:
            raise RuntimeError("Public Host MCP tool catalog drifted")
        status = _body(await client.call_tool("device_status", {}))
        devices = status.get("devices", [])
        if (
            status.get("runtime") != "host"
            or status.get("schema_version") != 1
            or sum(
                isinstance(d, dict)
                and d.get("device_id") == serial
                and d.get("state") == "device"
                for d in devices
            )
            != 1
        ):
            raise RuntimeError("Explicit device is not online and authorized")
        result = _body(
            await client.call_tool(
                "adb_observe", {"device_id": serial, "probes": probes}
            )
        )
        if (
            result.get("status") != "ok"
            or [entry["probe"] for entry in result.get("results", [])] != probes
        ):
            raise RuntimeError("Read-only observation did not fully complete")
        denied = _body(
            await client.call_tool(
                "adb_observe", {"device_id": "-s", "probes": ["identity"]}
            )
        )
        if denied.get("errors", [{}])[0].get("code") != "INVALID_DEVICE_ID":
            raise RuntimeError("Device ID validation gate failed")
        denied = _body(
            await client.call_tool(
                "adb_observe", {"device_id": "unknown-device", "probes": ["identity"]}
            )
        )
        if denied.get("errors", [{}])[0].get("code") != "DEVICE_NOT_FOUND":
            raise RuntimeError("Device isolation gate failed")
        denied = _body(
            await client.call_tool(
                "adb_develop", {"device_id": serial, "action": {"type": "raw_shell"}}
            )
        )
        if denied.get("errors", [{}])[0].get("code") != "UNKNOWN_OPERATION":
            raise RuntimeError("Action allowlist gate failed")
        summary = {
            "result": "pass",
            "transport": "loopback_http",
            "registered_tools": len(catalog),
            "authorized_device": True,
            "read_only_probes": probes,
            "denials": ["INVALID_DEVICE_ID", "DEVICE_NOT_FOUND", "UNKNOWN_OPERATION"],
            "device_output_persisted": False,
        }
        if log_lines is not None:
            log = _body(
                await client.call_tool(
                    "adb_develop",
                    {
                        "device_id": serial,
                        "action": {"type": "logcat_snapshot", "lines": log_lines},
                    },
                )
            )
            capture = log.get("result")
            if (
                log.get("status") not in {"ok", "partial"}
                or not isinstance(capture, dict)
                or len(capture.get("stdout", "")) > 25000
            ):
                raise RuntimeError("Bounded Logcat snapshot failed")
            summary["logcat_bounded"] = True
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device-id", required=True, help="Exact authorized ADB serial"
    )
    parser.add_argument(
        "--probes", nargs="+", choices=sorted(PROBES), default=DEFAULT_PROBES
    )
    parser.add_argument("--logcat-lines", type=int, default=None)
    args = parser.parse_args()
    if not valid_device_id(args.device_id):
        parser.error("Invalid device serial")
    if not 1 <= len(args.probes) <= MAX_PROBES or len(set(args.probes)) != len(
        args.probes
    ):
        parser.error("Choose 1 to 8 different probe groups")
    if args.logcat_lines is not None and not 10 <= args.logcat_lines <= 2000:
        parser.error("Logcat line count must be between 10 and 2000")

    port = _ephemeral_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "android_mcp_host", "serve", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        report = asyncio.run(
            asyncio.wait_for(
                _exercise(port, args.device_id, args.probes, args.logcat_lines),
                timeout=60,
            )
        )
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
    sys.exit(main())

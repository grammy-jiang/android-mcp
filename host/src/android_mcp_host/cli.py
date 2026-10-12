"""Portable CLI entry point; does not need an attached Android device."""

from __future__ import annotations

import argparse
import json
import platform

from android_mcp_host.adb import AdbClient
from android_mcp_host.server import create_server
from android_mcp_host.status import build_status, host_platform_name
from android_mcp_host.toolchain_inventory import ToolchainInventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="android-mcp-host")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Print read-only host/ADB diagnostics as JSON.")
    serve = subparsers.add_parser("serve", help="Start localhost-only Streamable HTTP MCP.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--toolchain-inventory",
        action="store_true",
        help="Opt in to a fixed-path read-only Host CLI inventory Tool.",
    )
    args = parser.parse_args(argv)

    if args.command == "doctor":
        print(json.dumps(build_status(AdbClient()), ensure_ascii=False, indent=2))
        return 0

    if args.host != "127.0.0.1":
        parser.error("Remote bind is disabled: --host must be 127.0.0.1.")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")
    if host_platform_name(platform.system()) == "unsupported":
        parser.error("Host runtime supports only macOS and Linux.")
    server = (
        create_server(toolchain_inventory=ToolchainInventory())
        if args.toolchain_inventory
        else create_server()
    )
    server.run(transport="http", host=args.host, port=args.port)
    return 0

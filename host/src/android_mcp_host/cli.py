"""Portable CLI entry point; does not need an attached Android device."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from typing import Any

from android_mcp_host.adb import AdbClient
from android_mcp_host.adb_transport import AdbTransport
from android_mcp_host.android_build_preflight import AndroidBuildPreflight
from android_mcp_host.capability_profiles import CapabilityProfiles
from android_mcp_host.device_discovery import DeviceDiscovery
from android_mcp_host.fastboot_inventory import FastbootInventory
from android_mcp_host.logcat_filters import LogcatFilters
from android_mcp_host.package_inspector import PackageInspector
from android_mcp_host.sdk_ndk_inventory import SdkNdkInventory
from android_mcp_host.server import create_server
from android_mcp_host.status import build_status, host_platform_name
from android_mcp_host.system_snapshot import SystemSnapshot
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
    serve.add_argument(
        "--capability-profile",
        choices=("safe", "diagnostic"),
        default=None,
        help="Opt in to an approved Host-only capability visibility profile.",
    )
    serve.add_argument(
        "--adb-devices-list",
        action="store_true",
        help="Opt in to bounded, read-only ADB device discovery.",
    )
    serve.add_argument(
        "--adb-transport-inspect",
        action="store_true",
        help="Opt in to bounded, read-only exact-target transport inspection.",
    )
    serve.add_argument(
        "--adb-system-snapshot",
        action="store_true",
        help="Opt in to fixed, typed, read-only Android system diagnostics.",
    )
    serve.add_argument(
        "--adb-package-inspect",
        action="store_true",
        help="Opt in to exact-package read-only version and permission diagnostics.",
    )
    serve.add_argument(
        "--adb-logcat-filter",
        action="store_true",
        help="Opt in to bounded Logcat capture with filtering and best-effort redaction.",
    )
    serve.add_argument(
        "--fastboot-inventory",
        action="store_true",
        help="Opt in to bounded Fastboot version and bootloader transport discovery only.",
    )
    serve.add_argument(
        "--sdk-ndk-inventory",
        action="store_true",
        help="Opt in to fixed read-only Android SDK/NDK/JDK workstation inventory.",
    )
    serve.add_argument(
        "--build-preflight",
        action="store_true",
        help="Opt in to a strictly inert, operator-pinned Android Gradle plan Tool.",
    )
    serve.add_argument(
        "--build-root",
        type=Path,
        default=None,
        help="Host-operator-selected absolute repository root, not an MCP Tool argument.",
    )
    serve.add_argument(
        "--build-approved-revision",
        default=None,
        help="Host-operator-pinned full Git commit SHA; otherwise preflight denies.",
    )
    serve.add_argument(
        "--build-wrapper-sha256",
        default=None,
        help="Host-operator-approved full Gradle wrapper jar SHA-256; otherwise denies.",
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
    inventory = (
        ToolchainInventory() if args.toolchain_inventory or args.capability_profile else None
    )
    kwargs: dict[str, Any] = {}
    if args.toolchain_inventory:
        kwargs["toolchain_inventory"] = inventory
    if args.capability_profile is not None:
        kwargs["capability_profiles"] = CapabilityProfiles(
            profile_ids=(args.capability_profile,),
            toolchain=inventory,
            inventory_enabled=bool(args.toolchain_inventory),
        )
    if args.adb_devices_list:
        kwargs["adb_discovery"] = DeviceDiscovery()
    if args.adb_transport_inspect:
        kwargs["adb_transport"] = AdbTransport()
    if args.adb_system_snapshot:
        kwargs["system_snapshot"] = SystemSnapshot()
    if args.adb_package_inspect:
        kwargs["package_inspector"] = PackageInspector()
    if args.adb_logcat_filter:
        kwargs["logcat_filter"] = LogcatFilters()
    if args.fastboot_inventory:
        kwargs["fastboot_inventory"] = FastbootInventory()
    if args.sdk_ndk_inventory:
        kwargs["sdk_ndk_inventory"] = SdkNdkInventory()
    if args.build_preflight:
        kwargs["build_preflight"] = AndroidBuildPreflight(
            root=args.build_root or (Path.home() / "Projects" / "android-mcp"),
            expected_revision=args.build_approved_revision,
            expected_wrapper_sha256=args.build_wrapper_sha256,
        )
    elif any((args.build_root, args.build_approved_revision, args.build_wrapper_sha256)):
        parser.error("Build pins require --build-preflight.")
    server = create_server(**kwargs)
    server.run(transport="http", host=args.host, port=args.port)
    return 0

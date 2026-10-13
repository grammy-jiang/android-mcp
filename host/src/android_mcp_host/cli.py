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
from android_mcp_host.archive_inspector import ArchiveInspector
from android_mcp_host.capability_profiles import CapabilityProfiles
from android_mcp_host.device_discovery import DeviceDiscovery
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.fastboot_inventory import FastbootInventory
from android_mcp_host.logcat_filters import LogcatFilters
from android_mcp_host.package_inspector import PackageInspector
from android_mcp_host.private_artifact_store import PrivateArtifactStore
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
    serve.add_argument(
        "--artifact-metadata",
        action="store_true",
        help="Opt in to owner-scoped, metadata-only private artifact inspection.",
    )
    serve.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Host-operator-selected absolute private artifact store root.",
    )
    serve.add_argument(
        "--artifact-owner",
        default=None,
        help="Trusted Host owner scope; never selectable by an MCP caller.",
    )
    serve.add_argument(
        "--archive-inspect",
        action="store_true",
        help="Opt in to owner-scoped private APK/AAB structure and signature status.",
    )
    serve.add_argument(
        "--apk-verifier",
        type=Path,
        default=None,
        help="Host-operator-pinned absolute apksigner executable; never caller-selected.",
    )
    serve.add_argument(
        "--aab-verifier",
        type=Path,
        default=None,
        help="Host-operator-pinned absolute jarsigner executable; never caller-selected.",
    )
    serve.add_argument(
        "--apk-metadata-tool",
        type=Path,
        default=None,
        help="Host-operator-pinned aapt2 binary for compiled APK manifest reads.",
    )
    serve.add_argument(
        "--aab-metadata-tool",
        type=Path,
        default=None,
        help="Host-operator-pinned bundletool wrapper for compiled AAB manifest reads.",
    )
    serve.add_argument(
        "--durable-job-status",
        action="store_true",
        help="Opt in to read-only owner-scoped persisted job status.",
    )
    serve.add_argument(
        "--job-root",
        type=Path,
        default=None,
        help="Host-operator-selected private job record directory.",
    )
    serve.add_argument(
        "--job-owner",
        default=None,
        help="Trusted Host owner scope for job metadata only.",
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
    if args.artifact_metadata:
        if (
            args.artifact_root is None
            or not args.artifact_root.is_absolute()
            or not PrivateArtifactStore.validate_owner(args.artifact_owner)
        ):
            parser.error("--artifact-metadata requires an absolute root and valid owner.")
        kwargs["artifact_store"] = PrivateArtifactStore(args.artifact_root)
        kwargs["artifact_owner"] = args.artifact_owner
    elif args.artifact_root is not None or args.artifact_owner is not None:
        parser.error("Private artifact options require --artifact-metadata.")
    if args.archive_inspect:
        if not args.artifact_metadata:
            parser.error("--archive-inspect requires --artifact-metadata.")
        kwargs["archive_inspector"] = ArchiveInspector(
            kwargs["artifact_store"],
            args.artifact_owner,
            apk_verifier=args.apk_verifier,
            aab_verifier=args.aab_verifier,
            apk_metadata_tool=args.apk_metadata_tool,
            aab_metadata_tool=args.aab_metadata_tool,
        )
    elif any(
        option is not None
        for option in (
            args.apk_verifier,
            args.aab_verifier,
            args.apk_metadata_tool,
            args.aab_metadata_tool,
        )
    ):
        parser.error("Verifier options require --archive-inspect.")
    if args.durable_job_status:
        if (
            args.job_root is None
            or not args.job_root.is_absolute()
            or not DurableJobStore.validate_owner(args.job_owner)
        ):
            parser.error("--durable-job-status requires an absolute root and valid owner.")
        kwargs["durable_jobs"] = DurableJobStore(args.job_root)
        kwargs["job_owner"] = args.job_owner
    elif args.job_root is not None or args.job_owner is not None:
        parser.error("Job store options require --durable-job-status.")
    server = create_server(**kwargs)
    server.run(transport="http", host=args.host, port=args.port)
    return 0

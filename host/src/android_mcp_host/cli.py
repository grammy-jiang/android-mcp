"""Portable CLI entry point; does not need an attached Android device."""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
from pathlib import Path
from typing import Any

from android_mcp_host.adb import AdbClient
from android_mcp_host.adb_transport import AdbTransport
from android_mcp_host.android_build_preflight import AndroidBuildPreflight
from android_mcp_host.archive_inspector import ArchiveInspector
from android_mcp_host.avd_inventory import AvdInventory
from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.capability_profiles import CapabilityProfiles
from android_mcp_host.controlled_build_jobs import ControlledBuildJobs
from android_mcp_host.device_discovery import DeviceDiscovery
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.emulator_snapshot_manager import EmulatorSnapshotManager
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
        "--emulator-snapshot-fixture",
        action="store_true",
        help="Opt in to private signed synthetic snapshot records; no real save or rollback.",
    )
    serve.add_argument(
        "--emulator-lifecycle-plan",
        action="store_true",
        help="Opt in to plan/status-only owned emulator Tool; real launch/stop disabled.",
    )
    serve.add_argument(
        "--avd-provision",
        action="store_true",
        help="Opt in to creating/deleting only dedicated MCP-owned synthetic AVD files.",
    )
    serve.add_argument("--avd-provision-root", type=Path, default=None)
    serve.add_argument("--avd-sdk-root", type=Path, default=None)
    serve.add_argument("--avd-owner", default=None)
    serve.add_argument("--avd-api", type=int, default=None)
    serve.add_argument(
        "--avd-abi",
        choices=("arm64-v8a", "armeabi-v7a", "x86", "x86_64"),
        default=None,
    )
    serve.add_argument("--avd-image-sha256", default=None)
    serve.add_argument("--avd-system-image-sha256", default=None)
    serve.add_argument("--avd-license-sha256", default=None)
    serve.add_argument(
        "--avd-inventory",
        action="store_true",
        help="Opt in to read-only operator-pinned AVD enumeration and metadata.",
    )
    serve.add_argument(
        "--avd-root",
        type=Path,
        default=None,
        help="Optional trusted absolute AVD store directory; no creation.",
    )
    serve.add_argument(
        "--avd-emulator",
        type=Path,
        default=None,
        help="Optional trusted absolute emulator executable; no startup.",
    )
    serve.add_argument(
        "--controlled-build",
        action="store_true",
        help="Opt in to bounded offline Gradle jobs using pinned private Host resources.",
    )
    serve.add_argument(
        "--build-timeout-seconds",
        type=float,
        default=None,
        help="Finite timeout 0-120 seconds; only for opt-in controlled builds.",
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
    if args.controlled_build:
        if args.build_timeout_seconds is not None and (
            not math.isfinite(args.build_timeout_seconds)
            or not 0 < args.build_timeout_seconds <= 120
        ):
            parser.error("--build-timeout-seconds must be within (0,120].")
        if (
            args.build_approved_revision is None
            or re.fullmatch(r"[0-9a-f]{40,64}", args.build_approved_revision) is None
            or args.build_wrapper_sha256 is None
            or re.fullmatch(r"[0-9a-f]{64}", args.build_wrapper_sha256) is None
        ):
            parser.error("--controlled-build requires valid pinned revision and wrapper SHA-256.")
        if (
            not args.build_preflight
            or args.build_root is None
            or not args.build_root.is_absolute()
            or args.build_approved_revision is None
            or args.build_wrapper_sha256 is None
            or not args.artifact_metadata
            or not args.durable_job_status
        ):
            parser.error(
                "--controlled-build requires --build-preflight and explicit pinned "
                "build root/revision/wrapper, artifact store and durable job store."
            )
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
    owned_config = (
        args.avd_provision_root,
        args.avd_sdk_root,
        args.avd_owner,
        args.avd_api,
        args.avd_abi,
        args.avd_image_sha256,
        args.avd_system_image_sha256,
        args.avd_license_sha256,
    )
    if args.emulator_snapshot_fixture and (
        not args.avd_provision or not args.durable_job_status or args.avd_owner != args.job_owner
    ):
        parser.error(
            "--emulator-snapshot-fixture needs pinned owned AVDs and durable jobs "
            "with matching trusted owner. Real emulator snapshot operations stay disabled."
        )
    if args.emulator_lifecycle_plan and (
        not args.avd_provision or not args.durable_job_status or args.avd_owner != args.job_owner
    ):
        parser.error(
            "--emulator-lifecycle-plan needs pinned AVD provisioning and job status "
            "with an identical trusted owner; real emulator execution remains disabled."
        )
    if args.avd_provision:
        if (
            any(value is None for value in owned_config)
            or not args.avd_provision_root.is_absolute()
            or not args.avd_sdk_root.is_absolute()
            or not PrivateArtifactStore.validate_owner(args.avd_owner)
            or not 16 <= args.avd_api <= 40
            or re.fullmatch(r"[0-9a-f]{64}", args.avd_image_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", args.avd_system_image_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", args.avd_license_sha256) is None
        ):
            parser.error("--avd-provision requires complete trusted absolute roots and SHA pins.")
        kwargs["avd_provisioner"] = AvdProvisioner(
            args.avd_provision_root,
            args.avd_sdk_root,
            args.avd_owner,
            api=args.avd_api,
            abi=args.avd_abi,
            source_properties_sha256=args.avd_image_sha256,
            system_image_sha256=args.avd_system_image_sha256,
            license_sha256=args.avd_license_sha256,
        )
    elif any(value is not None for value in owned_config):
        parser.error("Owned AVD provisioning options require --avd-provision.")
    if args.avd_inventory:
        root = args.avd_root or (Path.home() / ".android" / "avd")
        emulator = args.avd_emulator or (
            Path.home() / "Library" / "Android" / "sdk" / "emulator" / "emulator"
            if platform.system() == "Darwin"
            else Path.home() / "Android" / "Sdk" / "emulator" / "emulator"
        )
        if not root.is_absolute() or not emulator.is_absolute():
            parser.error("AVD root and emulator must be absolute trusted Host paths.")
        kwargs["avd_inventory"] = AvdInventory(root, emulator)
    elif args.avd_root is not None or args.avd_emulator is not None:
        parser.error("AVD store and emulator options require --avd-inventory.")
    if args.build_preflight:
        if args.build_root is not None and not args.build_root.is_absolute():
            parser.error("--build-root must be an absolute trusted Host project path.")
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
        kwargs["durable_jobs"] = DurableJobStore(
            args.job_root,
            lease_seconds=180.0 if args.controlled_build else 30.0,
        )
        kwargs["job_owner"] = args.job_owner
    elif args.job_root is not None or args.job_owner is not None:
        parser.error("Job store options require --durable-job-status.")
    if args.emulator_snapshot_fixture:
        kwargs["snapshot_manager"] = EmulatorSnapshotManager(
            kwargs["avd_provisioner"],
            kwargs["durable_jobs"],
            owner=args.avd_owner,
        )
    if args.emulator_lifecycle_plan:
        kwargs["emulator_lifecycle"] = EmulatorLifecycle(
            kwargs["avd_provisioner"],
            kwargs["durable_jobs"],
            owner=args.avd_owner,
        )
    if args.controlled_build:
        kwargs["build_jobs"] = ControlledBuildJobs(
            preflight=kwargs["build_preflight"],
            jobs=kwargs["durable_jobs"],
            artifacts=kwargs["artifact_store"],
            root=args.build_root,
            approved_revision=args.build_approved_revision,
            wrapper_sha256=args.build_wrapper_sha256,
            owner=args.job_owner,
            artifact_owner=args.artifact_owner,
            timeout_s=args.build_timeout_seconds
            if args.build_timeout_seconds is not None
            else 90.0,
        )
    elif args.build_timeout_seconds is not None:
        parser.error("--build-timeout-seconds requires --controlled-build.")
    server = create_server(**kwargs)
    server.run(transport="http", host=args.host, port=args.port)
    return 0

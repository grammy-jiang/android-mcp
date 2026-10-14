"""Operator CLI opt-ins for Host debug receipts and sensitive screenshot plans.

Never inject production fixture capture callbacks or real ADB media operations.
"""

from __future__ import annotations

import argparse
from typing import Any

from android_mcp_host.emulator_debug_deployment import DebugDeployment
from android_mcp_host.emulator_debug_support import valid_package
from android_mcp_host.file_pull_support import valid_synthetic_package
from android_mcp_host.synthetic_file_pull import FilePullService
from android_mcp_host.synthetic_file_push import FilePushService
from android_mcp_host.synthetic_screenrecord import ScreenRecordService
from android_mcp_host.synthetic_screenshot import ScreenshotArtifacts
from android_mcp_host.synthetic_ui_actions import UiActionService
from android_mcp_host.synthetic_ui_hierarchy import UiHierarchyService


def add_capture_flags(serve: argparse.ArgumentParser) -> None:
    serve.add_argument(
        "--emulator-debug-plan",
        action="store_true",
        help="Opt in to fake-only debug package planning; real ADB install stays disabled.",
    )
    serve.add_argument(
        "--debug-package-id",
        default=None,
        help="Operator-pinned synthetic debug package; never supplied by device discovery.",
    )
    serve.add_argument(
        "--screenshot-plan",
        action="store_true",
        help="Plan private synthetic screenshot capture; real capture remains disabled.",
    )
    serve.add_argument(
        "--ui-hierarchy-plan",
        action="store_true",
        help="Plan bounded redacted synthetic UI inspection; real UI access remains disabled.",
    )
    serve.add_argument(
        "--ui-action-plan",
        action="store_true",
        help="Opt in to scoped synthetic tap/swipe/key plans; real UI input disabled.",
    )
    serve.add_argument(
        "--screenrecord-plan",
        action="store_true",
        help="Opt in to private synthetic video planning; real ADB screenrecord stays disabled.",
    )
    serve.add_argument(
        "--file-pull-plan",
        action="store_true",
        help="Opt in to private synthetic app file-export plans; real pull stays disabled.",
    )
    serve.add_argument(
        "--file-pull-package-id",
        default=None,
        help="Operator-pinned synthetic export package (not an MCP argument).",
    )
    serve.add_argument(
        "--file-push-plan",
        action="store_true",
        help="Opt in to synthetic file-import plans; real Android push stays disabled.",
    )
    serve.add_argument(
        "--file-push-package-id",
        default=None,
        help="Operator-pinned synthetic import package; not a tool argument.",
    )


def validate_capture_flags(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.emulator_debug_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or not args.artifact_metadata
        or args.avd_owner != args.job_owner
        or not isinstance(args.debug_package_id, str)
        or not args.debug_package_id.startswith("org.example.synthetic.")
        or not valid_package(args.debug_package_id)
    ):
        parser.error(
            "--emulator-debug-plan requires pinned owner-scoped AVD, lifecycle, "
            "private artifacts, jobs and synthetic debug package. No real install."
        )
    if not args.emulator_debug_plan and args.debug_package_id is not None:
        parser.error("--debug-package-id requires --emulator-debug-plan.")
    if args.ui_hierarchy_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or args.avd_owner != args.job_owner
    ):
        parser.error("--ui-hierarchy-plan requires trusted owned AVD, lifecycle and job store.")
    if args.ui_action_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or not args.artifact_metadata
        or args.avd_owner != args.job_owner
    ):
        parser.error("--ui-action-plan requires owned AVD, lifecycle, jobs and artifacts.")
    if args.file_push_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or not args.artifact_metadata
        or args.avd_owner != args.job_owner
        or not valid_synthetic_package(args.file_push_package_id)
    ):
        parser.error("--file-push-plan requires private AVD, jobs, artifacts, synthetic package.")
    if not args.file_push_plan and args.file_push_package_id is not None:
        parser.error("--file-push-package-id requires --file-push-plan.")
    if args.file_pull_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or not args.artifact_metadata
        or args.avd_owner != args.job_owner
        or not valid_synthetic_package(args.file_pull_package_id)
    ):
        parser.error(
            "--file-pull-plan requires owned AVD, jobs, artifacts and a synthetic package."
        )
    if not args.file_pull_plan and args.file_pull_package_id is not None:
        parser.error("--file-pull-package-id requires --file-pull-plan.")
    if args.screenrecord_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or not args.artifact_metadata
        or args.avd_owner != args.job_owner
    ):
        parser.error("--screenrecord-plan requires owned AVD, lifecycle, jobs and artifacts.")
    if args.screenshot_plan and (
        not args.emulator_lifecycle_plan
        or not args.avd_provision
        or not args.durable_job_status
        or not args.artifact_metadata
        or args.avd_owner != args.job_owner
    ):
        parser.error(
            "--screenshot-plan requires trusted owned AVD, lifecycle, jobs and private artifacts."
        )


def register_capture_workers(args: argparse.Namespace, kwargs: dict[str, Any]) -> None:
    if args.emulator_debug_plan:
        kwargs["debug_deployment"] = DebugDeployment(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            kwargs["artifact_store"],
            owner=args.avd_owner,
            artifact_owner=args.artifact_owner,
            expected_package=args.debug_package_id,
        )
    if args.ui_hierarchy_plan:
        kwargs["ui_hierarchy_worker"] = UiHierarchyService(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            owner=args.avd_owner,
        )
    if args.ui_action_plan:
        kwargs["ui_action_worker"] = UiActionService(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            kwargs["artifact_store"],
            owner=args.avd_owner,
            artifact_owner=args.artifact_owner,
        )
    if args.file_push_plan:
        kwargs["file_push_worker"] = FilePushService(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            kwargs["artifact_store"],
            owner=args.avd_owner,
            artifact_owner=args.artifact_owner,
            package_id=args.file_push_package_id,
        )
    if args.file_pull_plan:
        kwargs["file_pull_worker"] = FilePullService(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            kwargs["artifact_store"],
            owner=args.avd_owner,
            artifact_owner=args.artifact_owner,
            package_id=args.file_pull_package_id,
        )
    if args.screenrecord_plan:
        kwargs["screenrecord_worker"] = ScreenRecordService(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            kwargs["artifact_store"],
            owner=args.avd_owner,
            artifact_owner=args.artifact_owner,
        )
    if args.screenshot_plan:
        kwargs["screenshot_worker"] = ScreenshotArtifacts(
            kwargs["avd_provisioner"],
            kwargs["emulator_lifecycle"],
            kwargs["durable_jobs"],
            kwargs["artifact_store"],
            owner=args.avd_owner,
            artifact_owner=args.artifact_owner,
        )

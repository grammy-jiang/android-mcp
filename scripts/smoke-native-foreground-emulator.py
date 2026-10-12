#!/usr/bin/env python3
"""Emulator-only Android 16 foreground service and MCP lifecycle acceptance.

Requires an explicit AVD serial and ro.kernel.qemu=1 *before* installing any
APK, starting Activities or manipulating permission state. Does not touch the
user's OnePlus Pad 3 or persist app/UI data or diagnostic logs.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import socket
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SCRIPT = ROOT / "scripts/smoke-native-emulator.py"
PACKAGE = "org.androidmcp.nativeapp"
ACTIVITY = f"{PACKAGE}/.NativeMcpActivity"
NOTIFICATION_PERMISSION = "android.permission.POST_NOTIFICATIONS"
START_SERVICE_SCREEN = "Open persistent service preview"
START_SERVICE_BUTTON = "Start background local MCP"
STOP_SERVICE_BUTTON = "Stop background local MCP"

spec = importlib.util.spec_from_file_location("native_mcp_emulator_core", CORE_SCRIPT)
assert spec is not None and spec.loader is not None
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def check_service_running(serial: str) -> None:
    """Confirm actual Android Service existence, not merely an open port."""
    details = core.adb(serial, "shell", "dumpsys", "activity", "services", PACKAGE)
    if "NativeMcpForegroundService" not in details:
        raise AssertionError("Android foreground service instance is missing")
    if (
        "isForeground=true" not in details
        or "foregroundId=23166" not in details
        or "foregroundNoti=Notification" not in details
    ):
        raise AssertionError("Android service was not actually promoted to foreground")


def get_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def identify_service_screen(xml: str) -> str:
    """Use exact, case-insensitive labels; reject unknown or occluded UI."""
    try:
        core.get_button_center(xml, START_SERVICE_BUTTON)
        core.get_button_center(xml, STOP_SERVICE_BUTTON)
        return "service"
    except ValueError:
        try:
            core.get_button_center(xml, START_SERVICE_SCREEN)
        except ValueError:
            return "unknown"
        return "launcher"


def open_service_screen(serial: str) -> None:
    """Handle Android task restoration to either Activity in the same task."""
    for _ in range(14):
        try:
            core.adb(serial, "shell", "uiautomator", "dump", core.UI_PATH, timeout=30)
            xml = core.adb(serial, "exec-out", "cat", core.UI_PATH)
            mode = identify_service_screen(xml)
            if mode == "service":
                return
            if mode == "launcher":
                x, y = core.get_button_center(xml, START_SERVICE_SCREEN)
                core.adb(serial, "shell", "input", "tap", str(x), str(y))
        except (RuntimeError, ValueError, ET.ParseError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Android app did not show the persistent service controls")


def run_emulator_service_test(serial: str, apk: Path) -> dict[str, object]:
    core.verify_emulator(serial)
    forwarded = False
    port = get_port()
    try:
        result = core.adb(serial, "install", "-r", str(apk), timeout=90)
        if "Success" not in result.splitlines():
            raise RuntimeError("Android emulator did not acknowledge APK installation")

        # First prove denial is safe. A user who refuses Android 13+
        # notification permission must not start this persistent service.
        core.adb(serial, "shell", "pm", "revoke", PACKAGE, NOTIFICATION_PERMISSION)
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        core.adb(serial, "shell", "wm", "dismiss-keyguard")
        core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        open_service_screen(serial)
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        time.sleep(0.5)
        dump = core.adb(serial, "shell", "dumpsys", "activity", "services", PACKAGE)
        if "NativeMcpForegroundService" in dump:
            raise AssertionError(
                "Service started despite denied notification permission"
            )
        # Dismiss the permission dialog without granting it via UI.
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")

        # Grant in this disposable emulator only, then require a second,
        # explicit user Start action. On real devices the user must approve.
        core.adb(serial, "shell", "pm", "grant", PACKAGE, NOTIFICATION_PERMISSION)
        core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        open_service_screen(serial)
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        core.adb(serial, "forward", "--no-rebind", f"tcp:{port}", "tcp:38765")
        forwarded = True
        endpoint = f"http://127.0.0.1:{port}/mcp"

        asyncio.run(core.await_running(endpoint))
        check_service_running(serial)

        # Unlike N2 Activity-only mode, the foreground service deliberately
        # stays alive with its notification when the app goes to background.
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        asyncio.run(core.await_running(endpoint))
        check_service_running(serial)

        core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        open_service_screen(serial)
        core.tap_ui_label(serial, STOP_SERVICE_BUTTON)
        asyncio.run(core.await_stopped(endpoint))

        # OS process termination must NOT automatically restart the service.
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        asyncio.run(core.await_running(endpoint))
        core.adb(serial, "shell", "am", "force-stop", PACKAGE)
        asyncio.run(core.await_stopped(endpoint))

        return {
            "result": "pass",
            "environment": "verified_emulator_only",
            "lifecycle": "user_started_specialUse_foreground_service",
            "physical_device_used": False,
            "mcp_tools": 1,
            "checks": [
                "install",
                "notification_permission_denial",
                "explicit_user_start",
                "foreground_notification_service",
                "mcp_status",
                "home_keeps_running",
                "user_stop_closes_listener",
                "process_force_stop_does_not_restart",
            ],
        }
    finally:
        try:
            core.adb(serial, "shell", "am", "force-stop", PACKAGE)
        finally:
            if forwarded:
                core.adb(serial, "forward", "--remove", f"tcp:{port}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", required=True, type=Path)
    args = parser.parse_args()
    try:
        core.require_emulator_serial(args.serial)
    except ValueError as error:
        parser.error(str(error))
    if not args.apk.is_file() or args.apk.stat().st_size < 10_000:
        parser.error("Valid compiled APK artifact required")
    report = run_emulator_service_test(args.serial, args.apk)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

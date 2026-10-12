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
NOTIFICATION_TITLE = "Android MCP local service"
NOTIFICATION_ID = 23166

spec = importlib.util.spec_from_file_location("native_mcp_emulator_core", CORE_SCRIPT)
assert spec is not None and spec.loader is not None
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

ROTATION_SCRIPT = ROOT / "scripts/smoke-native-orientation-emulator.py"
rotation_spec = importlib.util.spec_from_file_location(
    "native_n0c_fgs_rotation", ROTATION_SCRIPT
)
assert rotation_spec is not None and rotation_spec.loader is not None
rotation = importlib.util.module_from_spec(rotation_spec)
rotation_spec.loader.exec_module(rotation)


def assert_fgs_survives_real_orientation_change(serial: str, endpoint: str) -> None:
    """User-visible FGS must remain alive across real AVD display rotation."""
    api = int(core.adb(serial, "shell", "getprop", "ro.build.version.sdk").strip())
    rotation.validate_target(serial, api)
    original = rotation.original_rotation_settings(serial)
    before = rotation.actual_orientation(serial)
    try:
        rotation.set_rotation(serial, (before + 1) % 4)
        rotation.wait_orientation(serial, (before + 1) % 4)
        asyncio.run(core.assert_status(endpoint))
        check_service_running(serial)
    finally:
        rotation.restore_rotation(serial, original)


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


def has_ongoing_notification_record(notification_dump: str) -> bool:
    """Match the actual service notification, not the persistent channel."""
    for line in notification_dump.splitlines():
        if (
            "NotificationRecord(" in line
            and f"pkg={PACKAGE}" in line
            and f"id={NOTIFICATION_ID}" in line
        ):
            return True
    return False


def notification_stop_button_center(xml: str) -> tuple[int, int]:
    """Require the exact MCP notification title and an unambiguous Stop action."""
    labels = [node.attrib.get("text", "") for node in ET.fromstring(xml).iter("node")]
    if NOTIFICATION_TITLE not in labels:
        raise ValueError("The Android MCP foreground notification is not visible")
    return core.get_button_center(xml, "Stop")


def tap_notification_stop(serial: str) -> None:
    """Tap the real SystemUI action; no ADB service-intent shortcut."""
    core.adb(serial, "shell", "cmd", "statusbar", "expand-notifications")
    try:
        for _ in range(12):
            try:
                core.adb(
                    serial, "shell", "uiautomator", "dump", core.UI_PATH, timeout=30
                )
                xml = core.adb(serial, "exec-out", "cat", core.UI_PATH)
                x, y = notification_stop_button_center(xml)
                core.adb(serial, "shell", "input", "tap", str(x), str(y))
                return
            except (RuntimeError, ValueError, ET.ParseError):
                time.sleep(0.3)
        raise RuntimeError(
            "Android notification did not expose a unique MCP Stop action"
        )
    finally:
        core.adb(serial, "shell", "cmd", "statusbar", "collapse")


def assert_forward_present(serial: str, port: int) -> None:
    mapping = core.adb(serial, "forward", "--list")
    if f"tcp:{port} tcp:38765" not in mapping:
        raise AssertionError(
            "ADB forwarding disappeared; cannot prove Android shutdown"
        )


def await_android_service_and_notification_removed(serial: str) -> None:
    """Android-side oracle complements HTTP, which can also fail on network loss."""
    for _ in range(35):
        core.verify_emulator(serial)
        services = core.adb(serial, "shell", "dumpsys", "activity", "services", PACKAGE)
        notifications = core.adb(
            serial, "shell", "dumpsys", "notification", "--noredact"
        )
        if (
            "NativeMcpForegroundService" not in services
            and not has_ongoing_notification_record(notifications)
        ):
            return
        time.sleep(0.25)
    raise AssertionError("Android service or its ongoing notification was not removed")


def assert_fully_stopped(serial: str, port: int, endpoint: str) -> None:
    assert_forward_present(serial, port)
    asyncio.run(core.await_stopped(endpoint))
    assert_forward_present(serial, port)
    await_android_service_and_notification_removed(serial)


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


def assert_second_mode_is_rejected(serial: str, endpoint: str) -> None:
    """Legacy Activity must not steal the running FGS's sole loopback port."""
    core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
    open_service_screen(serial)
    core.adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")
    core.tap_ui_label(serial, "Start local read-only MCP")
    for _ in range(12):
        core.adb(serial, "shell", "uiautomator", "dump", core.UI_PATH, timeout=30)
        xml = core.adb(serial, "exec-out", "cat", core.UI_PATH)
        messages = [node.attrib.get("text") for node in ET.fromstring(xml).iter("node")]
        if "Could not start local MCP listener." in messages:
            asyncio.run(core.assert_status(endpoint))
            check_service_running(serial)
            return
        time.sleep(0.25)
    raise AssertionError("Competing Activity mode did not show its explicit rejection")


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
        assert_fgs_survives_real_orientation_change(serial, endpoint)

        # Unlike N2 Activity-only mode, the foreground service deliberately
        # stays alive with its notification when the app goes to background.
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        asyncio.run(core.await_running(endpoint))
        check_service_running(serial)

        # Re-enter Activity mode, deliberately request the same port and
        # verify a fail-closed denial without disrupting the FGS listener.
        assert_second_mode_is_rejected(serial, endpoint)
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_HOME")

        # Exercise the real SystemUI PendingIntent, not a shell-issued service
        # command or an in-app Stop button. Both Service and notification must
        # disappear; otherwise a transient HTTP outage is not a clean stop.
        tap_notification_stop(serial)
        assert_fully_stopped(serial, port, endpoint)

        # Also verify the in-app Stop path and explicit user restart.
        core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        open_service_screen(serial)
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        asyncio.run(core.await_running(endpoint))
        check_service_running(serial)
        core.tap_ui_label(serial, STOP_SERVICE_BUTTON)
        assert_fully_stopped(serial, port, endpoint)

        # Android process termination must NOT automatically restart it.
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        asyncio.run(core.await_running(endpoint))
        core.adb(serial, "shell", "am", "force-stop", PACKAGE)
        assert_fully_stopped(serial, port, endpoint)

        # N0.d: revoke the actual OS notification grant WHILE the explicitly
        # started foreground listener is running. Android may kill the app
        # when a runtime permission is revoked; regardless, its socket,
        # Android Service and notification must not survive as an orphan.
        core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        open_service_screen(serial)
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        asyncio.run(core.await_running(endpoint))
        check_service_running(serial)
        core.verify_emulator(serial)
        core.adb(serial, "shell", "pm", "revoke", PACKAGE, NOTIFICATION_PERMISSION)
        assert_fully_stopped(serial, port, endpoint)

        # The now-revoked permission may not be silently reused on a fresh
        # Activity START. A dialog is allowed; an active service is not.
        core.adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        open_service_screen(serial)
        core.tap_ui_label(serial, START_SERVICE_BUTTON)
        time.sleep(0.5)
        dump = core.adb(serial, "shell", "dumpsys", "activity", "services", PACKAGE)
        if "NativeMcpForegroundService" in dump:
            raise AssertionError("Service restarted with revoked notification consent")
        asyncio.run(core.await_stopped(endpoint))
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")
        # Restore to this script's explicitly approved disposable-AVD test
        # state; no physical app's permission may be modified.
        core.adb(serial, "shell", "pm", "grant", PACKAGE, NOTIFICATION_PERMISSION)

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
                "orientation_preserves_foreground_service",
                "mcp_status",
                "home_keeps_running",
                "competing_local_mode_rejected",
                "notification_stop_action_closes_listener",
                "android_service_and_notification_removed",
                "user_stop_closes_listener",
                "process_force_stop_does_not_restart",
                "revocation_closes_live_service_and_notification",
                "revoked_grant_denies_new_user_start",
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

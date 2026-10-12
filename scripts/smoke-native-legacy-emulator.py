#!/usr/bin/env python3
"""Validate N2 compatibility and N3 denial on explicit Android 11/13 AVDs.

Installs only into the specified QEMU-verified emulator; never picks an
implicit ADB target, changes a physical device, or grants app permissions.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts/smoke-native-emulator.py"
spec = importlib.util.spec_from_file_location("native_legacy_core", CORE)
assert spec is not None and spec.loader is not None
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

UNSUPPORTED_APIS = (30, 33)
N2_BUTTON = "Start local read-only MCP"
N3_BUTTON = "Open persistent service preview"
N3_UNSUPPORTED_MESSAGE = "Persistent MCP service requires Android 14 (API 34) or later."


def require_old_api(api: int) -> None:
    if api not in UNSUPPORTED_APIS:
        raise ValueError("Legacy N2 compatibility must target API 30 or 33")


def inspect_old_api_ui(xml: str) -> None:
    """Ensure unsupported N3 entry is disabled while N2 is still enabled."""
    root = ET.fromstring(xml)

    def button(label: str) -> dict[str, str]:
        matches = [
            node.attrib
            for node in root.iter("node")
            if node.attrib.get("text", "").strip().casefold() == label.casefold()
            and node.attrib.get("class") == "android.widget.Button"
        ]
        if len(matches) != 1:
            raise AssertionError(f"Expected exactly one {label!r} button")
        return matches[0]

    if button(N2_BUTTON).get("enabled") != "true":
        raise AssertionError("Legacy N2 MCP start is not available")
    if button(N3_BUTTON).get("enabled") != "false":
        raise AssertionError("Unsupported N3 foreground-service entry is enabled")

    messages = [
        node.attrib.get("text", "")
        for node in root.iter("node")
        if node.attrib.get("class") == "android.widget.TextView"
    ]
    if N3_UNSUPPORTED_MESSAGE not in messages:
        raise AssertionError("User-facing minimum Android version warning is missing")


def inspect_ui(serial: str) -> None:
    # A cold Android 11/13 first-launch may show Splash Screen or launcher
    # nodes for several UIAutomator snapshots. Wait only for actual N2
    # content; once visible, any safety-gate failure is terminal.
    for _ in range(35):
        try:
            core.adb(serial, "shell", "uiautomator", "dump", core.UI_PATH, timeout=30)
            xml = core.adb(serial, "exec-out", "cat", core.UI_PATH)
            root = ET.fromstring(xml)
        except (RuntimeError, ValueError, ET.ParseError):
            time.sleep(0.5)
            continue
        ready = any(
            node.attrib.get("class") == "android.widget.Button"
            and node.attrib.get("text", "").strip().casefold() == N2_BUTTON.casefold()
            and node.attrib.get("package") == core.PACKAGE
            for node in root.iter("node")
        )
        if ready:
            inspect_old_api_ui(xml)
            return
        time.sleep(0.5)
    raise AssertionError(
        "Old Android did not display Native N2 Activity within deadline"
    )


def verify_legacy_target(serial: str, expected_api: int) -> None:
    require_old_api(expected_api)
    core.verify_emulator(serial)
    actual = core.adb(serial, "shell", "getprop", "ro.build.version.sdk").strip()
    if actual != str(expected_api):
        raise ValueError(
            "Refusing to install on an emulator with unexpected Android API"
        )


def assert_no_foreground_service(serial: str) -> None:
    details = core.adb(serial, "shell", "dumpsys", "activity", "services", core.PACKAGE)
    if "NativeMcpForegroundService" in details:
        raise AssertionError(
            "N3 foreground Service should not be running on an old API"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="Explicit emulator-XXXX serial")
    parser.add_argument(
        "--expected-api", type=int, choices=UNSUPPORTED_APIS, required=True
    )
    parser.add_argument("--apk", required=True, type=Path)
    args = parser.parse_args()

    try:
        core.require_emulator_serial(args.serial)
    except ValueError as error:
        parser.error(str(error))
    if not args.apk.is_file() or args.apk.stat().st_size < 10_000:
        parser.error("Valid signed debug APK artifact required")

    verify_legacy_target(args.serial, args.expected_api)
    port = core.free_local_port()
    forwarded = False
    try:
        if (
            "Success"
            not in core.adb(
                args.serial, "install", "-r", str(args.apk), timeout=90
            ).splitlines()
        ):
            raise RuntimeError("Emulator did not confirm debug APK installation")
        core.adb(args.serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        core.adb(args.serial, "shell", "wm", "dismiss-keyguard")
        core.adb(args.serial, "shell", "am", "start", "-W", "-n", core.ACTIVITY)
        inspect_ui(args.serial)
        assert_no_foreground_service(args.serial)

        core.adb(args.serial, "forward", "--no-rebind", f"tcp:{port}", "tcp:38765")
        forwarded = True
        endpoint = f"http://127.0.0.1:{port}/mcp"
        core.click_start(args.serial)
        asyncio.run(core.await_running(endpoint))
        core.adb(args.serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        asyncio.run(core.await_stopped(endpoint))
        assert_no_foreground_service(args.serial)

        # Opening the original Activity again must allow the old N2 mode.
        core.adb(args.serial, "shell", "am", "start", "-W", "-n", core.ACTIVITY)
        inspect_ui(args.serial)
        core.click_start(args.serial)
        asyncio.run(core.await_running(endpoint))
        print(
            json.dumps(
                {
                    "result": "pass",
                    "environment": "verified_emulator_only",
                    "android_api": args.expected_api,
                    "n2_activity_mcp": "available",
                    "n2_home_stops": True,
                    "n3_foreground_entry": "disabled",
                    "n3_warning": "visible",
                    "n3_service_running": False,
                    "physical_device_used": False,
                },
                sort_keys=True,
            )
        )
    finally:
        try:
            core.adb(args.serial, "shell", "am", "force-stop", core.PACKAGE)
        finally:
            if forwarded:
                core.adb(args.serial, "forward", "--remove", f"tcp:{port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

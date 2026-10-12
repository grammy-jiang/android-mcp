#!/usr/bin/env python3
"""N0.c actual Android Activity orientation acceptance on a disposable AVD.

The exact emulator identity, boot and requested API are verified before any
app installation or settings modification. The script restores rotation
settings and its temporary ADB port forward on success AND failure.
Never accepts a physical target, an implicit ADB serial, or user credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_n0c_orientation_core", ROOT / "scripts/smoke-native-emulator.py"
)
assert SPEC is not None and SPEC.loader is not None
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

APIS = (30, 33, 34, 36)
ORIENTATION = re.compile(r"\bmCurrentOrientation=([0-3])\b")


def validate_target(serial: str, api: int) -> None:
    if api not in APIS:
        raise ValueError("Orientation acceptance requires API 30/33/34/36")
    core.require_emulator_serial(serial)
    core.verify_emulator(serial)
    if core.adb(serial, "shell", "getprop", "ro.build.version.sdk").strip() != str(api):
        raise ValueError("Expected API does not match verified disposable emulator")
    if core.adb(serial, "shell", "getprop", "sys.boot_completed").strip() != "1":
        raise ValueError("Target AVD is not boot complete")


def actual_orientation(serial: str) -> int:
    dump = core.adb(serial, "shell", "dumpsys", "display")
    values = ORIENTATION.findall(dump)
    if len(values) != 1:
        raise AssertionError("Could not prove one actual display orientation")
    return int(values[0])


def wait_orientation(serial: str, target: int) -> None:
    if target not in (0, 1, 2, 3):
        raise ValueError("Unknown display orientation")
    for _ in range(24):
        if actual_orientation(serial) == target:
            return
        time.sleep(0.25)
    raise AssertionError(
        "Emulator display failed to rotate to the requested orientation"
    )


def original_rotation_settings(serial: str) -> tuple[str, str]:
    auto = core.adb(
        serial, "shell", "settings", "get", "system", "accelerometer_rotation"
    ).strip()
    user = core.adb(
        serial, "shell", "settings", "get", "system", "user_rotation"
    ).strip()
    if auto not in ("0", "1") or user not in ("0", "1", "2", "3"):
        raise ValueError("Unrecognized preexisting emulator rotation settings")
    return auto, user


def set_rotation(serial: str, target: int) -> None:
    if target not in (0, 1, 2, 3):
        raise ValueError("Cannot set unrecognized screen orientation")
    core.adb(
        serial, "shell", "settings", "put", "system", "accelerometer_rotation", "0"
    )
    core.adb(serial, "shell", "settings", "put", "system", "user_rotation", str(target))


def restore_rotation(serial: str, original: tuple[str, str]) -> None:
    auto, user = original
    # Restore both settings rather than leaving landscape/user-rotation locks.
    core.adb(serial, "shell", "settings", "put", "system", "user_rotation", user)
    core.adb(
        serial, "shell", "settings", "put", "system", "accelerometer_rotation", auto
    )


def run(serial: str, api: int, apk: Path) -> dict[str, object]:
    validate_target(serial, api)
    if not apk.is_file() or apk.stat().st_size < 10_000:
        raise ValueError("Signed Native Android debug APK missing")
    original_settings = original_rotation_settings(serial)
    original_display = actual_orientation(serial)
    target = (original_display + 1) % 4
    forwarded = False
    rotated = False
    port = core.free_local_port()
    try:
        result = core.adb(serial, "install", "-r", str(apk), timeout=90)
        if "Success" not in result.splitlines():
            raise AssertionError(
                "Disposable emulator APK installation not acknowledged"
            )
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        core.adb(serial, "shell", "wm", "dismiss-keyguard")
        core.adb(serial, "shell", "am", "start", "-W", "-n", core.ACTIVITY)
        core.adb(serial, "forward", "--no-rebind", f"tcp:{port}", "tcp:38765")
        forwarded = True
        endpoint = f"http://127.0.0.1:{port}/mcp"
        core.click_start(serial)
        asyncio.run(core.await_running(endpoint))

        # Lock the emulator display one quarter-turn away from its actual
        # orientation, and independently verify Android's display rotation.
        rotated = True
        set_rotation(serial, target)
        wait_orientation(serial, target)

        # An Android configuration change stops/recreates N2 Activity;
        # the old listener may NOT silently survive that lifecycle event.
        asyncio.run(core.await_stopped(endpoint))
        core.click_start(serial)
        asyncio.run(core.await_running(endpoint))
        core.adb(serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        asyncio.run(core.await_stopped(endpoint))
        return {
            "result": "pass",
            "api": api,
            "checks": [
                "QEMU_and_exact_API",
                "real_display_rotation",
                "rotation_stops_activity_listener",
                "explicit_restart_required",
                "home_closes_listener",
                "restore_rotation_in_finally",
            ],
            "physical_device_used": False,
        }
    finally:
        # Every mutation above targets only the already verified QEMU serial.
        # Attempt rotation restoration even if the Android test itself fails.
        try:
            core.adb(serial, "shell", "am", "force-stop", core.PACKAGE)
        finally:
            try:
                if forwarded:
                    core.adb(serial, "forward", "--remove", f"tcp:{port}")
            finally:
                if rotated:
                    restore_rotation(serial, original_settings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--expected-api", required=True, type=int, choices=APIS)
    parser.add_argument("--apk", type=Path, required=True)
    args = parser.parse_args()
    outcome = run(args.serial, args.expected_api, args.apk)
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

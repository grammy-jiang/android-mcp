#!/usr/bin/env python3
"""N4.b: bounded tap, swipe and key to OWN TEST APP on verified QEMU only.

Never selects an implicit ADB device, physical USB target, other package or
Android system Settings. All actual input is restricted to one explicitly
verified disposable emulator while our own Activity is foreground. A
changed UI fingerprint or orientation requires fresh inspection. A failed
post-dispatch ADB operation is UNCERTAIN and is never automatically retried.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_n4b_core", ROOT / "scripts/smoke-native-emulator.py"
)
assert SPEC is not None and SPEC.loader is not None
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

OWN = "org.androidmcp.nativeapp"
ACTIVITY = f"{OWN}/.NativeMcpActivity"
START_BUTTON = "Start local read-only MCP"
APP_TITLE = "Android MCP Native — local preview"
UI_PATH = "/sdcard/android-mcp-n4b-ui.xml"
APIS = (30, 33, 34, 36)
ABIS = ("arm64-v8a", "x86_64")
ORIENTATION = re.compile(r"\bmCurrentOrientation=([0-3])\b")
DISPLAY = re.compile(r"Physical size:\s*(\d+)x(\d+)")
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


class UiSafetyError(RuntimeError):
    """Fixed denial; no untrusted Android UI/raw ADB output is exposed."""


@dataclass(frozen=True)
class UiProof:
    package: str
    rotation: int
    width: int
    height: int
    button_center: tuple[int, int]
    fingerprint: str
    state: str
    button_enabled: bool = True


def adb(serial: str, *args: str) -> str:
    """Reviewed, explicit serial only; never shell=True."""
    return core.adb(serial, *args)


def validate_target(serial: str, api: int, abi: str) -> None:
    try:
        core.require_emulator_serial(serial)
    except ValueError as error:
        raise UiSafetyError("Non-emulator Android serial refused") from error
    if api not in APIS or abi not in ABIS:
        raise UiSafetyError("Unsupported Android version or emulator ABI")
    checks = (
        (("get-state",), "device"),
        (("shell", "getprop", "ro.kernel.qemu"), "1"),
        (("shell", "getprop", "ro.build.version.sdk"), str(api)),
        (("shell", "getprop", "ro.product.cpu.abi"), abi),
        (("shell", "getprop", "sys.boot_completed"), "1"),
    )
    for command, expected in checks:
        try:
            actual = adb(serial, *command).strip()
        except (RuntimeError, OSError) as error:
            raise UiSafetyError("Emulator identity could not be verified") from error
        if actual != expected:
            raise UiSafetyError("Target is not an exact booted QEMU Android device")


def parse_owned_ui(xml: str, rotation: int, width: int, height: int) -> UiProof:
    if len(xml.encode("utf-8")) > 128 * 1024:
        raise UiSafetyError("UI snapshot exceeded size limit")
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise UiSafetyError("Entity or DTD in Android UI snapshot")
    if (
        rotation not in range(4)
        or width not in range(1, 8193)
        or height not in range(1, 8193)
    ):
        raise UiSafetyError("Unreasonable Android display geometry")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise UiSafetyError("Malformed emulator UI snapshot") from error
    if root.tag != "hierarchy":
        raise UiSafetyError("Unrecognized Android UI snapshot")
    own = [node for node in root.iter("node") if node.get("package") == OWN]
    if not any(node.get("text") == APP_TITLE for node in own):
        raise UiSafetyError("Expected Android MCP test app not visible")
    buttons = [
        node
        for node in own
        if node.get("class") == "android.widget.Button"
        and node.get("text", "").strip().casefold() == START_BUTTON.casefold()
    ]
    if len(buttons) != 1:
        raise UiSafetyError("Owned action button is ambiguous or missing")
    bound = BOUNDS.fullmatch(buttons[0].get("bounds", ""))
    if bound is None:
        raise UiSafetyError("Owned button has invalid geometry")
    left, top, right, bottom = (int(v) for v in bound.groups())
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise UiSafetyError("Owned button bounds are outside the display")
    # Refuse non-owned clickable/focusable overlays at action coordinates.
    # System status/navigation bars are elsewhere; a permission dialog or
    # malicious overlay covering our button makes the test unsafe.
    center_x, center_y = (left + right) // 2, (top + bottom) // 2
    swipe_x = 8
    swipe_top, swipe_bottom = height * 45 // 100, height * 60 // 100
    for foreign in root.iter("node"):
        if foreign.get("package") == OWN or not (
            foreign.get("clickable") == "true" or foreign.get("focusable") == "true"
        ):
            continue
        other = BOUNDS.fullmatch(foreign.get("bounds", ""))
        if other is None:
            raise UiSafetyError("Untrusted interactive overlay has unknown bounds")
        x1, y1, x2, y2 = (int(v) for v in other.groups())
        covers_tap = x1 <= center_x < x2 and y1 <= center_y < y2
        covers_swipe = x1 <= swipe_x < x2 and y1 < swipe_bottom and y2 > swipe_top
        if covers_tap or covers_swipe:
            raise UiSafetyError("Interactive non-owned overlay blocks safe action")
    status = [
        node.get("text", "")
        for node in own
        if node.get("class") == "android.widget.TextView"
    ]
    if any(line.startswith("Running on 127.0.0.1:38765/mcp") for line in status):
        state = "running"
    elif any(line.startswith("Stopped.") for line in status):
        state = "stopped"
    elif any(line.startswith("Starting local-only MCP...") for line in status):
        state = "starting"
    else:
        raise UiSafetyError("Unexpected Android test Activity state")
    normalized = [
        (node.get("class"), node.get("text"), node.get("enabled"), node.get("bounds"))
        for node in own
    ]
    digest = hashlib.sha256(
        repr((rotation, width, height, normalized)).encode("utf-8")
    ).hexdigest()
    return UiProof(
        OWN,
        rotation,
        width,
        height,
        ((left + right) // 2, (top + bottom) // 2),
        digest,
        state,
        buttons[0].get("enabled") == "true",
    )


def guarded_input(
    serial: str,
    api: int,
    abi: str,
    proof: UiProof,
    operation: str,
    current_ui: Callable[[], UiProof],
) -> str:
    validate_target(serial, api, abi)
    try:
        current = current_ui()
    except (RuntimeError, OSError) as error:
        raise UiSafetyError("Could not re-inspect owned Android UI") from error
    if proof != current or proof.package != OWN:
        raise UiSafetyError(
            "Window, rotation or hierarchy changed: reinspection required"
        )
    if proof.button_center[0] not in range(proof.width) or proof.button_center[
        1
    ] not in range(proof.height):
        raise UiSafetyError("Action geometry outside verified display")
    if operation == "tap":
        if proof.state != "stopped" or not proof.button_enabled:
            raise UiSafetyError("Owned Start button is not currently tappable")
        parts = (
            "shell",
            "input",
            "tap",
            str(proof.button_center[0]),
            str(proof.button_center[1]),
        )
    elif operation == "swipe":
        start_y = proof.height * 45 // 100
        end_y = proof.height * 60 // 100
        if start_y >= end_y or proof.width < 16:
            raise UiSafetyError("No safe empty region to swipe")
        # X=8 is left of the owned Activity's padded, clickable controls.
        parts = ("shell", "input", "swipe", "8", str(start_y), "8", str(end_y), "180")
    elif operation == "key":
        if proof.state != "running":
            raise UiSafetyError("Navigation-key test requires active own app")
        # DPAD_DOWN only moves focus; never BACK/HOME/ENTER/POWER.
        parts = ("shell", "input", "keyevent", "KEYCODE_DPAD_DOWN")
    else:
        raise UiSafetyError("Unreviewed Android UI action denied")
    try:
        adb(serial, *parts)
    except (RuntimeError, OSError, KeyboardInterrupt):
        # One dispatch may have occurred before transport loss/interruption.
        # Never automatically retry a potentially non-idempotent UI input.
        return "uncertain"
    return "sent"


def cleanup_app(serial: str, api: int, abi: str) -> None:
    validate_target(serial, api, abi)
    try:
        adb(serial, "shell", "am", "force-stop", OWN)
    finally:
        # Remove only our single, fixed test-owned UI dump. Never clear
        # external storage or data belonging to another application.
        adb(serial, "shell", "rm", "-f", UI_PATH)


def owned_screen(serial: str, api: int, abi: str) -> UiProof:
    validate_target(serial, api, abi)
    activity = adb(serial, "shell", "dumpsys", "activity", "activities")
    top = [
        line
        for line in activity.splitlines()
        if "topResumedActivity=" in line or "mResumedActivity:" in line
    ]
    if not any(OWN in line and "NativeMcpActivity" in line for line in top):
        raise UiSafetyError("Own Android test Activity is not top-resumed")
    window_dump = adb(serial, "shell", "dumpsys", "window")
    focused = [line for line in window_dump.splitlines() if "mCurrentFocus=" in line]
    if len(focused) != 1 or OWN not in focused[0]:
        raise UiSafetyError("Actual focused Android window is not our app")
    display = adb(serial, "shell", "wm", "size")
    match = DISPLAY.search(display)
    rotation_data = adb(serial, "shell", "dumpsys", "display")
    rotation = ORIENTATION.findall(rotation_data)
    if match is None or len(rotation) != 1:
        raise UiSafetyError("Could not prove physical display geometry and rotation")
    width, height = (int(x) for x in match.groups())
    adb(serial, "shell", "uiautomator", "dump", UI_PATH)
    raw = adb(serial, "exec-out", "cat", UI_PATH)
    return parse_owned_ui(raw, int(rotation[0]), width, height)


def wait_owned_state(serial: str, api: int, abi: str, state: str) -> UiProof:
    for _ in range(24):
        try:
            proof = owned_screen(serial, api, abi)
        except UiSafetyError:
            time.sleep(0.4)
            continue
        if proof.state == state:
            return proof
        time.sleep(0.4)
    raise UiSafetyError("Owned Android Activity did not reach expected state")


def run(serial: str, api: int, abi: str, apk: Path) -> dict[str, object]:
    # No APK install, input or cleanup until this exact QEMU target is proven.
    validate_target(serial, api, abi)
    # Never let a caller point the runner at an arbitrary third-party APK:
    # only the artifact produced by this exact Native repo/worktree is valid.
    approved_apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    if (
        apk.is_symlink()
        or apk.resolve() != approved_apk.resolve()
        or not apk.is_file()
        or apk.suffix != ".apk"
        or apk.stat().st_size < 10_000
    ):
        raise UiSafetyError("Only this worktree's owned Native debug APK is permitted")
    installed = False
    try:
        result = adb(serial, "install", "-r", str(apk.resolve()))
        if "Success" not in result.splitlines():
            raise UiSafetyError("Disposable AVD did not acknowledge APK install")
        installed = True
        cleanup_app(serial, api, abi)  # clear *only* our app session
        adb(serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        stopped = wait_owned_state(serial, api, abi, "stopped")
        if (
            guarded_input(
                serial, api, abi, stopped, "tap", lambda: owned_screen(serial, api, abi)
            )
            != "sent"
        ):
            raise UiSafetyError("Tap dispatch uncertain; no automatic retry")
        running = wait_owned_state(serial, api, abi, "running")
        # The same Activity's transition from Stopped to Running invalidates
        # the first UI proof. Reject the stale plan BEFORE sending any input.
        try:
            guarded_input(
                serial,
                api,
                abi,
                stopped,
                "tap",
                lambda: owned_screen(serial, api, abi),
            )
        except UiSafetyError:
            pass
        else:
            raise UiSafetyError("Stale owned-UI action was not refused")
        if (
            guarded_input(
                serial,
                api,
                abi,
                running,
                "swipe",
                lambda: owned_screen(serial, api, abi),
            )
            != "sent"
        ):
            raise UiSafetyError("Swipe dispatch uncertain; no automatic retry")
        still_running = wait_owned_state(serial, api, abi, "running")
        if (
            guarded_input(
                serial,
                api,
                abi,
                still_running,
                "key",
                lambda: owned_screen(serial, api, abi),
            )
            != "sent"
        ):
            raise UiSafetyError("Key dispatch uncertain; no automatic retry")
        wait_owned_state(serial, api, abi, "running")
        return {
            "result": "pass",
            "api": api,
            "abi": abi,
            "checks": [
                "strict_qemu_api_abi_boot",
                "owned_activity_tap",
                "stale_owned_ui_denied",
                "bounded_swipe",
                "navigation_key",
                "owned_state_remains",
            ],
            "target": "verified_emulator_only",
            "physical_android_used": False,
        }
    finally:
        if installed:
            cleanup_app(serial, api, abi)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--expected-api", type=int, required=True, choices=APIS)
    parser.add_argument("--expected-abi", required=True, choices=ABIS)
    parser.add_argument("--apk", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.serial, args.expected_api, args.expected_abi, args.apk),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

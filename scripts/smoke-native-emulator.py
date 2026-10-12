#!/usr/bin/env python3
"""Real Android MCP lifecycle smoke on an explicit disposable emulator only.

The script installs a debug APK in a verified AVD, taps the user-visible
start button, tests real HTTP MCP, verifies HOME stops the listener, and
relaunches. No physical-device commands, arbitrary ADB shell or raw UI logs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from fastmcp import Client
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
STATUS_SCHEMA = ROOT / "contracts/device-status.v1.schema.json"
PACKAGE = "org.androidmcp.nativeapp"
ACTIVITY = f"{PACKAGE}/.NativeMcpActivity"
AVD_SERIAL = re.compile(r"emulator-[0-9]{4,6}\Z")
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\Z")
UI_PATH = "/sdcard/android-mcp-emulator-test.xml"
CAPTURE_LIMIT = 128 * 1024


def require_emulator_serial(serial: str) -> None:
    if not AVD_SERIAL.fullmatch(serial):
        raise ValueError(
            "Explicit Android emulator serial required; physical devices forbidden"
        )


def require_virtual_target(flag: str) -> None:
    if flag.strip() != "1":
        raise ValueError("Android kernel does not identify as an emulator")


def get_button_center(xml: str) -> tuple[int, int]:
    matches: list[tuple[int, int]] = []
    for node in ET.fromstring(xml).iter("node"):
        if node.attrib.get("text") != "Start local read-only MCP":
            continue
        bound = BOUNDS.fullmatch(node.attrib.get("bounds", ""))
        if bound is None:
            raise ValueError("Start button has malformed bounds")
        x1, y1, x2, y2 = (int(s) for s in bound.groups())
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Start button has empty bounds")
        matches.append(((x1 + x2) // 2, (y1 + y2) // 2))
    if len(matches) != 1:
        raise ValueError("Exactly one unambiguous start button required")
    return matches[0]


def adb(serial: str, *args: str, timeout: int = 25) -> str:
    require_emulator_serial(serial)
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, *args],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Emulator ADB unavailable or timed out") from error
    if proc.returncode or len(proc.stdout) + len(proc.stderr) > CAPTURE_LIMIT:
        raise RuntimeError("Emulator ADB command failed or exceeded output budget")
    return proc.stdout


def verify_emulator(serial: str) -> None:
    require_emulator_serial(serial)
    try:
        discovery = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=12, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("ADB device discovery failed") from error
    if not any(row.split()[:2] == [serial, "device"] for row in discovery.splitlines()):
        raise ValueError("Explicit emulator is not online/authorized")
    require_virtual_target(adb(serial, "shell", "getprop", "ro.kernel.qemu"))


def click_start(serial: str) -> None:
    for _ in range(12):
        try:
            adb(serial, "shell", "uiautomator", "dump", UI_PATH, timeout=30)
            x, y = get_button_center(adb(serial, "exec-out", "cat", UI_PATH))
            adb(serial, "shell", "input", "tap", str(x), str(y))
            return
        except (RuntimeError, ValueError, ET.ParseError):
            time.sleep(1)
    raise RuntimeError("Android app did not render its explicit start button")


async def assert_status(url: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        if [tool.name for tool in tools] != ["device_status"]:
            raise AssertionError("Unexpected Native MCP tool catalog")
        result = await client.call_tool("device_status", {})
        if result.is_error or len(result.content) != 1:
            raise AssertionError("On-device status tool failed")
        text = getattr(result.content[0], "text", None)
        if not isinstance(text, str) or len(text) > CAPTURE_LIMIT:
            raise AssertionError("On-device status output malformed or oversized")
        payload = json.loads(text)
        Draft202012Validator(json.loads(STATUS_SCHEMA.read_text())).validate(payload)
        caps = payload["capabilities"]
        if (
            payload["runtime"] != "android"
            or payload["devices"]
            or payload["errors"]
            or caps.get("android.native.loopback_status") is not True
            or any(
                caps.get(key) is not False
                for key in (
                    "android.accessibility.observe",
                    "android.accessibility.act",
                    "android.privileged",
                )
            )
        ):
            raise AssertionError(
                "Native MCP status capability/privacy contract drifted"
            )


async def await_running(url: str) -> None:
    last_type = "NotReady"
    for _ in range(65):
        try:
            await asyncio.wait_for(assert_status(url), timeout=4)
            return
        except (
            Exception
        ) as exc:  # Startup failures can be SDK-specific exception groups
            # Never retry semantic/schema failures: transient transport only.
            if isinstance(exc, (AssertionError, ValueError, ValidationError)):
                raise
            last_type = type(exc).__name__
            await asyncio.sleep(0.5)
    raise RuntimeError(f"Android MCP never became ready: {last_type}")


async def await_stopped(url: str) -> None:
    # Open a fresh MCP session each attempt: a persistent old session could
    # accidentally mask the shutdown of the server's listening socket.
    for _ in range(18):
        try:
            await asyncio.wait_for(assert_status(url), timeout=2)
        except Exception as exc:  # Disconnected MCP sessions vary by transport
            if isinstance(exc, (AssertionError, ValueError, ValidationError)):
                raise
            return
        await asyncio.sleep(0.5)
    raise AssertionError("Android MCP still responds after Activity.onStop")


def free_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", required=True, type=Path)
    args = parser.parse_args()
    try:
        require_emulator_serial(args.serial)
    except ValueError as error:
        parser.error(str(error))
    if not args.apk.is_file() or args.apk.stat().st_size < 10_000:
        parser.error("Required APK not present")

    verify_emulator(args.serial)
    port = free_local_port()
    forwarded = False
    try:
        if "Success" not in adb(
            args.serial, "install", "-r", str(args.apk), timeout=90
        ):
            raise RuntimeError("Emulator did not confirm APK install")
        adb(args.serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        adb(args.serial, "shell", "wm", "dismiss-keyguard")
        adb(args.serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        adb(args.serial, "forward", "--no-rebind", f"tcp:{port}", "tcp:38765")
        forwarded = True
        endpoint = f"http://127.0.0.1:{port}/mcp"

        click_start(args.serial)
        asyncio.run(await_running(endpoint))
        adb(args.serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        asyncio.run(await_stopped(endpoint))
        adb(args.serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
        click_start(args.serial)
        asyncio.run(await_running(endpoint))
        print(
            json.dumps(
                {
                    "result": "pass",
                    "environment": "verified_emulator_only",
                    "transport": "adb_forward_to_local_mcp",
                    "registered_tools": 1,
                    "checks": ["install", "http_status", "home_stops", "resume_starts"],
                    "physical_device_used": False,
                },
                sort_keys=True,
            )
        )
    finally:
        # All test cleanup is restricted to this previously verified AVD.
        try:
            adb(args.serial, "shell", "am", "force-stop", PACKAGE)
        finally:
            if forwarded:
                adb(args.serial, "forward", "--remove", f"tcp:{port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

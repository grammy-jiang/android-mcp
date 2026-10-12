#!/usr/bin/env python3
"""Opt-in, fail-closed N3 Android API matrix runner for disposable AVDs only.

Preflight verifies *all four* explicit AVDs before any install or UI action.
API 30/33 must retain N2 and deny N3; API 34/36 must pass N2 and N3.
No physical device serial is accepted or implicitly selected.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

API_VERSIONS = (30, 33, 34, 36)
SERIAL_PATTERN = re.compile(r"emulator-[0-9]{4,6}\Z")
ROOT = Path(__file__).resolve().parents[1]
MAX_ADB_OUTPUT_BYTES = 4096
MAX_SMOKE_OUTPUT_BYTES = 16_384


class MatrixSafetyError(RuntimeError):
    """A required emulator identity, preflight, or smoke failed."""


def validate_assignments(assignments: dict[int, str]) -> None:
    if set(assignments) != set(API_VERSIONS):
        raise MatrixSafetyError("Exactly API 30, 33, 34 and 36 targets are required")
    values = list(assignments.values())
    if any(SERIAL_PATTERN.fullmatch(serial) is None for serial in values):
        raise MatrixSafetyError("Only explicit emulator-XXXX ADB serials are allowed")
    if len(set(values)) != len(values):
        raise MatrixSafetyError(
            "Every Android API must have a distinct emulator serial"
        )


def invoke(argv: list[str], timeout: int, max_bytes: int) -> str:
    """Single bounded no-shell subprocess wrapper; does not mutate arguments."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MatrixSafetyError(
            "Verification subprocess failed or timed out"
        ) from error
    if len(result.stdout.encode()) + len(result.stderr.encode()) > max_bytes:
        raise MatrixSafetyError("Verification subprocess exceeded output limit")
    if result.returncode != 0:
        # Avoid echoing untrusted device/ADB/system logs in a shared CI context.
        raise MatrixSafetyError(
            f"Verification subprocess failed (exit code {result.returncode})"
        )
    return result.stdout.strip()


def adb_read(serial: str, *args: str) -> str:
    if SERIAL_PATTERN.fullmatch(serial) is None:
        raise MatrixSafetyError("ADB target is not an explicit Android emulator")
    return invoke(["adb", "-s", serial, *args], 15, MAX_ADB_OUTPUT_BYTES)


def verify_all_before_any_mutation(
    assignments: dict[int, str],
    adb_reader: Callable[..., str] = adb_read,
) -> None:
    """Fail the entire run if even one AVD fails identity preflight."""
    validate_assignments(assignments)
    for expected_api in API_VERSIONS:
        serial = assignments[expected_api]
        if adb_reader(serial, "get-state") != "device":
            raise MatrixSafetyError(f"API {expected_api} AVD is not online")
        if adb_reader(serial, "shell", "getprop", "ro.kernel.qemu") != "1":
            raise MatrixSafetyError(f"API {expected_api} target is not QEMU")
        actual_api = adb_reader(serial, "shell", "getprop", "ro.build.version.sdk")
        if actual_api != str(expected_api):
            raise MatrixSafetyError(
                f"API mismatch: expected {expected_api}, emulator says {actual_api!r}"
            )
        if adb_reader(serial, "shell", "getprop", "sys.boot_completed") != "1":
            raise MatrixSafetyError(f"API {expected_api} Android is not fully booted")


def commands_for(api: int, serial: str, apk: Path) -> list[list[str]]:
    """Construct only reviewed scripts with exact emulator-target arguments."""
    if api not in API_VERSIONS or SERIAL_PATTERN.fullmatch(serial) is None:
        raise MatrixSafetyError("Unsupported API or non-emulator target")
    apk_path = str(apk.resolve())
    if api in (30, 33):
        return [
            [
                sys.executable,
                str(ROOT / "scripts/smoke-native-legacy-emulator.py"),
                "--serial",
                serial,
                "--expected-api",
                str(api),
                "--apk",
                apk_path,
            ]
        ]
    return [
        [
            sys.executable,
            str(ROOT / "scripts/smoke-native-emulator.py"),
            "--serial",
            serial,
            "--apk",
            apk_path,
        ],
        [
            sys.executable,
            str(ROOT / "scripts/smoke-native-foreground-emulator.py"),
            "--serial",
            serial,
            "--apk",
            apk_path,
        ],
    ]


def run_matrix(
    assignments: dict[int, str],
    apk: Path,
    adb_reader: Callable[..., str] = adb_read,
    command_runner: Callable[[list[str], int, int], str] = invoke,
) -> list[dict[str, object]]:
    if not apk.is_file() or apk.stat().st_size < 10_000 or apk.suffix != ".apk":
        raise MatrixSafetyError("A locally built, nonempty .apk file is required")
    # This whole loop must happen before any subprocess installs an APK.
    verify_all_before_any_mutation(assignments, adb_reader)
    results: list[dict[str, object]] = []
    for api in API_VERSIONS:
        steps = commands_for(api, assignments[api], apk)
        step_outputs = []
        for command in steps:
            # The child scripts reverify emulator identity immediately before
            # mutation; this outer check is an additional fail-closed fence.
            output = command_runner(command, 420, MAX_SMOKE_OUTPUT_BYTES)
            if '"result": "pass"' not in output:
                raise MatrixSafetyError(
                    f"API {api} smoke did not report an explicit PASS"
                )
            step_outputs.append(command[1].rsplit("/", 1)[-1])
        results.append(
            {
                "api": api,
                "target": "verified_emulator_only",
                "result": "pass",
                "suites": step_outputs,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for api in API_VERSIONS:
        parser.add_argument(
            f"--api{api}", required=True, help=f"Explicit API {api} emulator serial"
        )
    parser.add_argument("--apk", type=Path, required=True)
    args = parser.parse_args()
    assignments = {api: getattr(args, f"api{api}") for api in API_VERSIONS}
    try:
        result = run_matrix(assignments, args.apk)
    except MatrixSafetyError as error:
        print(f"NATIVE_API_MATRIX_FAILED: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"result": "pass", "android_matrix": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

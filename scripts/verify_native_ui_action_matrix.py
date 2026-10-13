#!/usr/bin/env python3
"""N4.b matrix: all four exact QEMU/API/ABI targets before ANY UI input.

Runs the reviewed owned-app-only tap/swipe/DPAD_DOWN smoke serially. Never
touches physical Android, system Settings, non-owned apps or arbitrary ADB
command strings. No implicit ADB serial, no fallback on failure.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_n4b_matrix_base", ROOT / "scripts/verify_native_api_matrix.py"
)
assert SPEC is not None and SPEC.loader is not None
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)

ACTION = ROOT / "scripts/smoke-native-ui-action-emulator.py"


class UiMatrixError(RuntimeError):
    """Fixed error code; never expose adb stdout or private Android UI."""


def commands_for(api: int, serial: str, abi: str, apk: Path) -> list[str]:
    if api not in base.API_VERSIONS or not base.SERIAL_PATTERN.fullmatch(serial):
        raise UiMatrixError("Non-emulator or unknown API rejected")
    if abi not in ("arm64-v8a", "x86_64"):
        raise UiMatrixError("Unknown Android emulator ABI rejected")
    return [
        sys.executable,
        str(ACTION),
        "--serial",
        serial,
        "--expected-api",
        str(api),
        "--expected-abi",
        abi,
        "--apk",
        str(apk.resolve()),
    ]


def run_matrix(
    assignments: dict[int, str],
    abi: str,
    apk: Path,
    *,
    reader: Callable[..., str] = base.adb_read,
    runner: Callable[[list[str], int, int], str] = base.invoke,
) -> list[dict[str, object]]:
    if not apk.is_file() or apk.stat().st_size < 10_000 or apk.suffix != ".apk":
        raise UiMatrixError("Signed test APK not available")
    # All four must pass QEMU/online/API/boot checks before any install/input.
    base.verify_all_before_any_mutation(assignments, reader)
    if abi not in ("arm64-v8a", "x86_64"):
        raise UiMatrixError("Unknown emulator ABI")
    for api in base.API_VERSIONS:
        actual = reader(assignments[api], "shell", "getprop", "ro.product.cpu.abi")
        if actual != abi:
            raise UiMatrixError("One emulator ABI does not match the expected ABI")

    results: list[dict[str, object]] = []
    for api in base.API_VERSIONS:
        output = runner(
            commands_for(api, assignments[api], abi, apk),
            240,
            16_384,
        )
        try:
            row = json.loads(output)
        except (TypeError, ValueError) as error:
            raise UiMatrixError("Malformed owned UI acceptance result") from error
        if (
            not isinstance(row, dict)
            or row.get("result") != "pass"
            or row.get("target") != "verified_emulator_only"
            or row.get("physical_android_used") is not False
            or row.get("api") != api
            or row.get("abi") != abi
            or set(row.get("checks", []))
            != {
                "strict_qemu_api_abi_boot",
                "owned_activity_tap",
                "stale_owned_ui_denied",
                "bounded_swipe",
                "navigation_key",
                "owned_state_remains",
            }
        ):
            raise UiMatrixError("AVD input smoke result was not proven")
        results.append(
            {
                "api": api,
                "result": "pass",
                "target": "verified_emulator_only",
                "checks": row["checks"],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for api in base.API_VERSIONS:
        parser.add_argument(f"--api{api}", required=True)
    parser.add_argument("--abi", required=True, choices=("arm64-v8a", "x86_64"))
    parser.add_argument("--apk", required=True, type=Path)
    args = parser.parse_args()
    assignments = {api: getattr(args, f"api{api}") for api in base.API_VERSIONS}
    result = run_matrix(assignments, args.abi, args.apk)
    print(
        json.dumps(
            {
                "result": "pass",
                "physical_android_used": False,
                "target": "verified_disposable_qemu_only",
                "android_ui_matrix": result,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

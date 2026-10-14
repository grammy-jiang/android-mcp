#!/usr/bin/env python3
"""E01 owned-disposable-AVD four-version instrumentation + real MCP harness.

ADB installs a pinned debug application/test APK as test setup and separately
observes Android state. ADB NEVER substitutes as a Native MCP Tool executor.
No physical device, external interface, grant/approval bypass, wipe or root.

Tests run serially under a per-AVD nonblocking OS lock. Never reuse someone
else's emulator by serial alone; verify fresh AVD owner, process, boot identity.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class IdentityError(ValueError):
    """An AVD or process cannot prove disposable exclusive ownership."""


def _require(assertion: bool, message: str) -> None:
    if not assertion:
        raise IdentityError(message)


def validate_identity(owner: dict[str, Any], observed: dict[str, Any]) -> None:
    """Pure functional admission; test first, inspect right before any install."""
    _require(owner.get("disposable") is True, "Not a declared disposable AVD")
    name = owner.get("avd")
    serial = owner.get("expected_serial")
    api = owner.get("expected_api")
    _require(
        isinstance(name, str)
        and bool(
            re.fullmatch(r"android_mcp_native_v3_api(30|33|34|36)_20[0-9]{6}", name)
        ),
        "Unknown or non-owned AVD",
    )
    _require(
        owner.get("worktree", "").startswith("android-mcp-native-v3-"),
        "Wrong owner worktree",
    )
    _require(owner.get("host") == socket.gethostname(), "Wrong owner workstation")
    _require(
        isinstance(serial, str) and bool(re.fullmatch(r"emulator-55[0-9]{2}", serial)),
        "Physical/malformed serial",
    )
    _require(isinstance(api, int) and api in (30, 33, 34, 36), "Unapproved Android API")
    _require(name == f"android_mcp_native_v3_api{api}_20261014", "Wrong AVD marker/API")
    _require(
        owner.get("pid", 0) > 0 and isinstance(owner.get("pid"), int),
        "No owned emulator PID",
    )
    _require(observed.get("serial") == serial, "Serial changed")
    _require(observed.get("avd") == name, "AVD identity mismatch")
    _require(observed.get("api") == api, "SDK mismatch")
    _require(observed.get("qemu") == "1", "Physical device or unverifiable emulator")
    _require(observed.get("abi") == "arm64-v8a", "Unknown ABI")
    _require(observed.get("boot_completed") == "1", "Device not fully booted")
    boot = observed.get("boot_identity")
    _require(
        isinstance(boot, str)
        and bool(
            re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot
            )
        ),
        "Missing device kernel boot epoch",
    )
    process = observed.get("process")
    _require(isinstance(process, str) and "qemu-system-" in process, "Not QEMU process")
    _require(
        f"-avd {name}" in process and f"-port {serial.split('-')[1]}" in process,
        "Emulator process does not own expected AVD/port",
    )


@contextlib.contextmanager
def exclusive_avd_lock(path: Path) -> Iterator[None]:
    """Fail immediately if another local test holds this shared OS lock."""
    with path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _run(argv: list[str], timeout: int = 45, max_bytes: int = 128 * 1024) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"Test subprocess failed or timed out: {argv[0]}") from exc
    if result.returncode:
        raise RuntimeError(
            f"Test process {Path(argv[0]).name} exit={result.returncode}: "
            f"{result.stderr[:300].decode('utf-8', 'replace')}"
        )
    if len(result.stdout) + len(result.stderr) > max_bytes:
        raise RuntimeError("Evidence subprocess exceeded 128KiB output budget")
    return result.stdout.decode("utf-8", "replace")


def _adb(serial: str, *args: str, timeout: int = 45) -> str:
    if not re.fullmatch(r"emulator-55[0-9]{2}", serial):
        raise IdentityError("Refusing to execute ADB against physical device")
    return _run(["adb", "-s", serial, *args], timeout)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _owner_and_device(api: int) -> tuple[dict[str, Any], dict[str, Any], Path]:
    name = f"android_mcp_native_v3_api{api}_20261014"
    avd = Path.home() / ".android" / "avd" / f"{name}.avd"
    manifest = Path.home() / ".android" / "avd" / f"{name}.ini"
    owner_path = avd / "v3-owner.json"
    if not avd.is_dir() or not manifest.is_file() or not owner_path.is_file():
        raise IdentityError("AVD marker missing; do not adopt external device")
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    if owner.get("expected_api") != api:
        raise IdentityError("AVD marker API mismatch")
    pid = owner.get("pid")
    if not isinstance(pid, int) or pid < 1:
        raise IdentityError("No emulator PID")
    process = _run(["ps", "-p", str(pid), "-o", "command="], timeout=10).strip()
    serial = owner["expected_serial"]
    actual_avd = _adb(serial, "emu", "avd", "name").strip().splitlines()[0]
    observed = {
        "serial": serial,
        "avd": actual_avd,
        "api": int(_adb(serial, "shell", "getprop", "ro.build.version.sdk").strip()),
        "qemu": _adb(serial, "shell", "getprop", "ro.kernel.qemu").strip(),
        "abi": _adb(serial, "shell", "getprop", "ro.product.cpu.abi").strip(),
        "boot_completed": _adb(
            serial, "shell", "getprop", "sys.boot_completed"
        ).strip(),
        "boot_identity": _adb(
            serial, "shell", "cat", "/proc/sys/kernel/random/boot_id"
        ).strip(),
        "process": process,
    }
    validate_identity(owner, observed)
    return owner, observed, avd


def _git(path: Path, arg: str) -> str:
    return _run(["git", "-C", str(path), "rev-parse", arg], timeout=10).strip()


def run_for_api(
    api: int, repo: Path, python: Path, apk: Path, test_apk: Path, evidence_dir: Path
) -> dict[str, Any]:
    owner, _, avd = _owner_and_device(api)
    with exclusive_avd_lock(avd / "v3-test-exclusive.lock"):
        # Check identity again AFTER lock: first read was just to locate lock.
        owner, observed, _ = _owner_and_device(api)
        serial = owner["expected_serial"]
        if not all(p.is_file() and p.stat().st_size > 10_000 for p in (apk, test_apk)):
            raise RuntimeError("Pinned built APKs unavailable")
        # Test setup, not Native operation.
        for package in (apk, test_apk):
            if (
                _adb(serial, "install", "-r", str(package), timeout=90)
                .strip()
                .splitlines()[-1]
                != "Success"
            ):
                raise RuntimeError("APK installation was not confirmed")
        os_package = _adb(
            serial, "shell", "dumpsys", "package", "org.androidmcp.nativeapp"
        )
        if "versionCode=1 minSdk=30 targetSdk=36" not in os_package:
            raise RuntimeError(
                "Installed package/version mismatched independent OS oracle"
            )
        tests = _adb(
            serial,
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            "org.androidmcp.nativeapp.test/androidx.test.runner.AndroidJUnitRunner",
            timeout=90,
        )
        if "OK (3 tests)" not in tests or "INSTRUMENTATION_CODE: -1" not in tests:
            raise RuntimeError("AndroidJUnitRunner did not pass all on-device cases")
        # MCP client calls real APK. ADB here exclusively launches the app and
        # presses UI buttons; it does not execute the requested MCP status Tool.
        mcp_out = _run(
            [
                str(python),
                str(repo / "scripts/smoke-native-emulator.py"),
                "--serial",
                serial,
                "--apk",
                str(apk),
            ],
            timeout=100,
        )
        result = json.loads(mcp_out)
        if result.get("result") != "pass" or result.get("registered_tools") != 1:
            raise RuntimeError("Native real MCP client failed or catalog drifted")
        receipt = {
            "run_type": "V3_E01_BASELINE_NOT_PRODUCT_ACCEPTANCE",
            "api": api,
            "emulator": serial,
            "avd": observed["avd"],
            "abi": observed["abi"],
            "boot_identity": observed["boot_identity"],
            "emulator_pid": owner["pid"],
            "git_head": _git(repo, "HEAD"),
            "git_tree": _git(repo, "HEAD^{tree}"),
            "apk_sha256": _sha(apk),
            "instrumentation_apk_sha256": _sha(test_apk),
            "instrumentation_tests": 3,
            "mcp_client": "FastMCP to installed Native Android APK",
            "mcp_check": result,
            "independent_android_oracle": "PackageManager installed version/UID",
            "n01_emulator_function_done": False,
            "timestamp_unix": int(time.time()),
            "notes": "Unauthenticated status-only baseline; no writes or consent bypass",
        }
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = evidence_dir / f"native-v3-e01-api{api}-{receipt['timestamp_unix']}.json"
        with path.open("x", encoding="utf-8") as output:
            json.dump(receipt, output, indent=2, sort_keys=True)
            output.write("\n")
        path.chmod(0o600)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=int, choices=(30, 33, 34, 36), required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--instrumentation-apk", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = run_for_api(
        args.api,
        args.repo.resolve(),
        args.python.absolute(),
        args.apk.resolve(),
        args.instrumentation_apk.resolve(),
        args.evidence_dir.resolve(),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IdentityError, RuntimeError, OSError, ValueError) as exc:
        print(f"E01_FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

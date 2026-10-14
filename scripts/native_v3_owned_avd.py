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
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from scripts.native_v3_avd_attestation import (
    IdentityError,
    _owner_canonical_bytes,
    _require,
    atomic_create_owner_proof,
    create_owner_attestation,
    parse_owned_forward_routes,
    read_lab_owner_secret,
    read_owner_proof,
    validate_identity,
    validate_test_run_nonce,
    verify_owner_attestation,
)

# Preserve public helper imports for existing provision/test callers.
__all__ = [
    "EXPECTED_NATIVE_ANDROID_TEST_NAMES",
    "IdentityError",
    "assert_forward_cleanup",
    "atomic_create_owner_proof",
    "create_owner_attestation",
    "exclusive_avd_lock",
    "parse_owned_forward_routes",
    "read_lab_owner_secret",
    "read_owner_proof",
    "validate_identity",
    "validate_test_run_nonce",
    "verify_native_instrumentation_report",
    "verify_owner_attestation",
]

EXPECTED_NATIVE_ANDROID_TEST_NAMES = frozenset(
    {
        "installedApplicationIsObservableThroughRealPackageManager",
        "installedManifestHasExplicitLocalPreviewAndNoPrivilegedWildcard",
        "realSystemServicesAreAccessibleWithoutPrivilegedConsent",
        "realInstalledAppKeystoreCreatesNonexportablePersistentPrivateKey",
        "genuineKeystoreSignatureVerifiesButForgedPeerCannotEnroll",
        "privateInstallationRecordSurvivesClosingOneOwnerWithoutNewIdentity",
        "secondConcurrentActivityOwnerIsRejectedUntilLockReleased",
        "actualAndroidReopensPersistedFenceAndRetainsNoMutationAuthority",
    }
)


def verify_native_instrumentation_report(text: str) -> list[str]:
    """Require exact on-device methods, not a fraudulent tests-passed count."""
    if (
        not isinstance(text, str)
        or len(text) > 128 * 1024
        or "FAILURES!!!" in text
        or "INSTRUMENTATION_CODE: -1" not in text
        or "OK (8 tests)" not in text
    ):
        raise RuntimeError("AndroidJUnitRunner output is not a complete genuine run")
    methods = re.findall(r"(?m)^INSTRUMENTATION_STATUS: test=([A-Za-z0-9_]+)$", text)
    if set(methods) != EXPECTED_NATIVE_ANDROID_TEST_NAMES or len(methods) != 16:
        raise RuntimeError(
            "Native Android test names, count or execution callbacks drifted"
        )
    if any(methods.count(name) != 2 for name in EXPECTED_NATIVE_ANDROID_TEST_NAMES):
        raise RuntimeError(
            "Native AndroidJUnitRunner missing start/end method callbacks"
        )
    return sorted(EXPECTED_NATIVE_ANDROID_TEST_NAMES)


@contextlib.contextmanager
def exclusive_avd_lock(path: Path) -> Iterator[None]:
    """Exclusive owned AVD lock; never follow a symlink or truncate data."""
    _require(path.parent.is_dir() and not path.is_symlink(), "Invalid owner lock path")
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise IdentityError("Could not open exclusive AVD lock safely") from exc
    try:
        info = os.fstat(fd)
        _require(
            stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(),
            "AVD lock is not an owned regular file",
        )
        # Existing mode 0644 owner-created lock files can be tightened safely;
        # do not remove or replace the existing inode another test holds.
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "r+b") as lock:
            fd = -1
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        if fd >= 0:
            os.close(fd)


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


def _owner_and_device(
    api: int, *, require_attestation: bool = True
) -> tuple[dict[str, Any], dict[str, Any], Path]:
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
    started = _run(["ps", "-p", str(pid), "-o", "lstart="], timeout=10).strip()
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
        "process_start": started,
    }
    validate_identity(owner, observed)
    if require_attestation:
        proof = read_owner_proof(avd / "v3-owner-proof.v1.json")
        key = read_lab_owner_secret(
            Path.home() / ".android/avd/v3-attestation-key.v1", create=False
        )
        verify_owner_attestation(proof, owner, observed, started, key, int(time.time()))
        observed["owner_attestation_nonce"] = proof["nonce"]
        observed["owner_attestation_sha256"] = hashlib.sha256(
            _owner_canonical_bytes(proof)
        ).hexdigest()
    return owner, observed, avd


def _git(path: Path, arg: str) -> str:
    return _run(["git", "-C", str(path), "rev-parse", arg], timeout=10).strip()


def run_for_api(
    api: int,
    repo: Path,
    python: Path,
    apk: Path,
    test_apk: Path,
    evidence_dir: Path,
    run_nonce: str | None = None,
) -> dict[str, Any]:
    run_nonce = validate_test_run_nonce(run_nonce or secrets.token_hex(16))
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
        executed_android_methods = verify_native_instrumentation_report(tests)
        # MCP client calls real APK. ADB here exclusively launches the app and
        # presses UI buttons; it does not execute the requested MCP status Tool.
        with assert_forward_cleanup(serial):
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
            "owner_attestation_nonce": observed["owner_attestation_nonce"],
            "owner_attestation_sha256": observed["owner_attestation_sha256"],
            "run_nonce": run_nonce,
            "git_head": _git(repo, "HEAD"),
            "git_tree": _git(repo, "HEAD^{tree}"),
            "apk_sha256": _sha(apk),
            "instrumentation_apk_sha256": _sha(test_apk),
            "instrumentation_tests": len(executed_android_methods),
            "instrumentation_method_ids": executed_android_methods,
            "forward_cleanup_verified": True,
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


def _owned_forward_snapshot(serial: str) -> tuple[str, ...]:
    return parse_owned_forward_routes(_adb(serial, "forward", "--list"), serial)


@contextlib.contextmanager
def assert_forward_cleanup(serial: str) -> Iterator[None]:
    """Detect leftover Android MCP forwards even when tool run fails.

    No unscoped forward --remove-all: such cleanup could tear down another
    Host's active development. Preserve a failure as a required GAP until
    an owner verifies the exact orphaned mapping.
    """
    baseline = _owned_forward_snapshot(serial)
    try:
        yield
    finally:
        after = _owned_forward_snapshot(serial)
        if baseline != after:
            raise RuntimeError("Owned emulator MCP forward mapping leaked/changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=int, choices=(30, 33, 34, 36), required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--instrumentation-apk", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--run-nonce", type=str)
    args = parser.parse_args()
    receipt = run_for_api(
        args.api,
        args.repo.resolve(),
        args.python.absolute(),
        args.apk.resolve(),
        args.instrumentation_apk.resolve(),
        args.evidence_dir.resolve(),
        args.run_nonce,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IdentityError, RuntimeError, OSError, ValueError) as exc:
        print(f"E01_FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

#!/usr/bin/env python3
"""E01.b independent verification of signed, user-data-free Android fixtures.

Installs signed fixture APKs to already-owned disposable emulators only.
Tests fixture UI with ADB as a test user and content oracle; NOT a Native
MCP Tool side effect, PackageInstaller grant, screen capture Tool, or N08 pass.

Run: python3 -m scripts.native_v3_fixture_matrix --api 36 --repo .
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.native_v3_owned_avd import (
    _adb,
    _owner_and_device,
    _run,
    _sha,
    exclusive_avd_lock,
)

FIXTURE = "org.androidmcp.v3fixture"
INSTALL_TARGET = "org.androidmcp.v3installfixture"
ORACLE_URI = "content://org.androidmcp.v3fixture.oracle/counter"
DOCUMENT_URI = "content://org.androidmcp.v3fixture.documents/document/known-document"
ACCESSIBILITY_ID = "android-mcp-v3-increment-counter"
PALETTE = ((255, 64, 80), (21, 203, 131), (22, 137, 255))
EXPECTED_DOC_SHA = hashlib.sha256(b"ANDROID-MCP-V3-FIXTURE-DOCUMENT-v1\n").hexdigest()


class FixtureVerificationError(ValueError):
    """Unexpected fixture operation, observation or provenance."""


def parse_counter(text: str) -> int:
    match = re.fullmatch(r"Row: 0 counter=([0-9]{1,7})\s*", text)
    if not match:
        raise FixtureVerificationError("Not one authentic fixture counter row")
    return int(match.group(1))


def parse_signer_digest(text: str) -> str:
    matches = re.findall(
        r"^Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})\s*$",
        text,
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        raise FixtureVerificationError("APK not signed by exactly one parseable signer")
    return matches[0]


def locate_button(xml: str) -> tuple[int, int]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise FixtureVerificationError("UI hierarchy invalid") from exc
    candidates = [
        item
        for item in root.iter()
        if item.attrib.get("content-desc") == ACCESSIBILITY_ID
        and item.attrib.get("class") == "android.widget.Button"
        and item.attrib.get("enabled") != "false"
    ]
    if len(candidates) != 1:
        raise FixtureVerificationError("Fixture button missing or ambiguous")
    bounds = candidates[0].attrib.get("bounds", "")
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not match:
        raise FixtureVerificationError("Malformed fixture button bounds")
    x1, y1, x2, y2 = (int(v) for v in match.groups())
    if not (x2 > x1 >= 0 and y2 > y1 >= 0):
        raise FixtureVerificationError("Unusable fixture button bounds")
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def match_pixel(pixel: str, rgb: tuple[int, int, int]) -> bool:
    match = re.fullmatch(r"srgba?\((\d+),(\d+),(\d+),(1(?:\.0+)?)\)", pixel)
    if not match:
        return False
    actual = tuple(int(v) for v in match.groups()[:3])
    return all(abs(a - b) <= 4 for a, b in zip(actual, rgb, strict=True))


def valid_documents_denial(text: str, exitcode: int) -> bool:
    # Android's 'content' command can exit zero on an uncaught Java
    # SecurityException, so never use the shell return code as sole proof.
    return (
        exitcode in (0, 1)
        and "java.lang.SecurityException: Permission Denial:" in text
        and "ACTION_OPEN_DOCUMENT" in text
        and "FixtureDocumentsProvider" in text
    )


def _run_capture(
    argv: list[str], *, timeout: int = 25
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, capture_output=True, timeout=timeout, check=False)


def _require(predicate: bool, why: str) -> None:
    if not predicate:
        raise FixtureVerificationError(why)


def _file_checks(apk: Path, installer: Path, sdk: Path) -> dict[str, str]:
    signer = sdk / "build-tools/36.0.0/apksigner"
    aapt = sdk / "build-tools/36.0.0/aapt"
    _require(
        signer.is_file() and aapt.is_file(), "Pinned Android build tools 36.0.0 absent"
    )
    results = {}
    for title, path, package in (
        ("fixture", apk, FIXTURE),
        ("install_target", installer, INSTALL_TARGET),
    ):
        _require(path.is_file() and path.stat().st_size > 10_000, "Fixture APK absent")
        certs = _run([str(signer), "verify", "--print-certs", str(path)], timeout=15)
        results[title + "_sha256"] = _sha(path)
        results[title + "_certificate_sha256"] = parse_signer_digest(certs)
        badging = _run([str(aapt), "dump", "badging", str(path)], timeout=15)
        _require(
            f"package: name='{package}' versionCode='1'" in badging,
            "Fixture package/version mismatch",
        )
        permissions = _run([str(aapt), "dump", "permissions", str(path)], timeout=15)
        _require(
            "uses-permission:" not in permissions,
            "Fixture requests Android permissions",
        )
    _require(
        results["fixture_certificate_sha256"]
        == results["install_target_certificate_sha256"],
        "Fixture and installer target must share this test-lab signing identity",
    )
    return results


def _adb_oracle(serial: str) -> int:
    return parse_counter(_adb(serial, "shell", "content", "query", "--uri", ORACLE_URI))


def _screenshot_palette(serial: str) -> str:
    with tempfile.TemporaryDirectory(prefix="android-mcp-v3-fixture-") as tmp:
        screenshot = Path(tmp) / "emulator-fixture.png"
        binary = _run_capture(["adb", "-s", serial, "exec-out", "screencap", "-p"])
        _require(
            binary.returncode == 0
            and binary.stdout.startswith(b"\x89PNG\r\n\x1a\n")
            and len(binary.stdout) < 12 * 1024 * 1024,
            "Fixture screenshot not genuine PNG from owned device",
        )
        screenshot.write_bytes(binary.stdout)
        size = _run(["magick", "identify", "-format", "%w %h", str(screenshot)])
        match = re.fullmatch(r"(\d+) (\d+)", size)
        _require(match is not None, "ImageMagick cannot inspect screenshots")
        width, height = (int(v) for v in match.groups())
        _require(
            700 <= width <= 4200 and 700 <= height <= 4200,
            "Unexpected screenshot shape",
        )
        y = int(height * 0.40)
        for x_percent, expected in zip((0.22, 0.5, 0.8), PALETTE, strict=True):
            x = int(width * x_percent)
            pixel = _run(
                [
                    "magick",
                    str(screenshot),
                    "-format",
                    f"%[pixel:p{{{x},{y}}}]",
                    "info:",
                ],
            ).strip()
            _require(
                match_pixel(pixel, expected),
                f"Unrecognized fixture pixel at {x},{y}: {pixel}",
            )
        return hashlib.sha256(binary.stdout).hexdigest()


def verify_fixture(api: int, repo: Path, evidence_dir: Path) -> dict[str, object]:
    # Same exact exclusive AVD as V3 Native check; never adopt shared/physical
    # Android serial by CLI parameter or mere emulator-xxxx shape.
    owner, _, avd = _owner_and_device(api)
    with exclusive_avd_lock(avd / "v3-test-exclusive.lock"):
        owner, observed, _ = _owner_and_device(api)
        serial = owner["expected_serial"]
        sdk = Path.home() / "Library/Android/sdk"
        apk = (
            repo
            / "android/native-v3-fixture/build/outputs/apk/debug/native-v3-fixture-debug.apk"
        )
        installer = (
            repo / "android/native-v3-install-fixture/build/outputs/apk/debug/"
            "native-v3-install-fixture-debug.apk"
        )
        test_apk = (
            repo / "android/native-v3-fixture/build/outputs/apk/androidTest/debug/"
            "native-v3-fixture-debug-androidTest.apk"
        )
        signatures = _file_checks(apk, installer, sdk)
        _require(test_apk.is_file(), "Missing fixture test APK")
        for path in (apk, test_apk):
            install_output = _adb(serial, "install", "-r", str(path), timeout=70)
            _require(
                install_output.strip().splitlines()[-1] == "Success",
                "Fixture install failed",
            )
        package = _adb(serial, "shell", "dumpsys", "package", FIXTURE)
        _require(
            "versionCode=1 minSdk=30 targetSdk=36" in package, "Android PM disagrees"
        )
        instrumentation = _adb(
            serial,
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            f"{FIXTURE}.test/androidx.test.runner.AndroidJUnitRunner",
            timeout=75,
        )
        _require(
            "OK (9 tests)" in instrumentation
            and "INSTRUMENTATION_CODE: -1" in instrumentation,
            "Fixture AndroidJUnitRunner behavior suite failed",
        )
        denial = _run_capture(
            ["adb", "-s", serial, "shell", "content", "query", "--uri", DOCUMENT_URI]
        )
        denial_text = (denial.stdout + denial.stderr).decode("utf-8", "replace")
        _require(
            valid_documents_denial(denial_text, denial.returncode),
            "Unapproved direct documents provider read was not denied",
        )
        before = _adb_oracle(serial)
        _adb(serial, "shell", "am", "start", "-n", f"{FIXTURE}/.FixtureActivity")
        # Wait for Android activity, UI and compositor, not just am start ACK.
        screenshot_sha = None
        last_error = ""
        for _ in range(15):
            time.sleep(0.5)
            try:
                screenshot_sha = _screenshot_palette(serial)
                break
            except (RuntimeError, FixtureVerificationError) as exc:
                last_error = str(exc)
        _require(
            screenshot_sha is not None,
            "Fixture known-pixel oracle failed: " + last_error,
        )
        _adb(
            serial,
            "shell",
            "uiautomator",
            "dump",
            "/sdcard/native-v3-fixture-hierarchy.xml",
            timeout=20,
        )
        ui = _adb(serial, "exec-out", "cat", "/sdcard/native-v3-fixture-hierarchy.xml")
        x, y = locate_button(ui)
        # This is an external test user's ADB gesture, *not* Native MCP UI control.
        _adb(serial, "shell", "input", "tap", str(x), str(y), timeout=15)
        after = _adb_oracle(serial)
        _require(
            after == before + 1,
            f"Fixture touch did not change persistent oracle: {before}→{after}",
        )
        # Verified disposable fixture process death; the stable counter must
        # be re-observable after a fresh framework-launched process.
        _adb(serial, "shell", "am", "force-stop", FIXTURE)
        _adb(serial, "shell", "am", "start", "-n", f"{FIXTURE}/.FixtureActivity")
        post_restart = _adb_oracle(serial)
        _require(
            post_restart == after,
            f"Fixture counter lost across process death: {after}→{post_restart}",
        )
        receipt = {
            "scope": "E01.b TEST_FIXTURE_ONLY_NOT_NATIVE_FEATURE",
            "status": "FIXTURE_READY",
            "api": api,
            "serial": serial,
            "avd": observed["avd"],
            "boot_identity": observed["boot_identity"],
            "emulator_pid": owner["pid"],
            "signing": signatures,
            "androidTest_sha256": _sha(test_apk),
            "document_bytes_sha256": EXPECTED_DOC_SHA,
            "instrumentation": "9 real AndroidJUnitRunner tests",
            "external_counter_before": before,
            "external_counter_after": after,
            "counter_after_process_restart": post_restart,
            "os_direct_document_denied": True,
            "independent_screenshot_sha256": screenshot_sha,
            "visual_colors": PALETTE,
            "installer_target": "signed APK validated, NOT installed by Native PackageInstaller",
            "actual_native_mcp_tool_used": False,
            "product_case_passed": False,
            "git_head": _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip(),
            "git_tree": _run(
                ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]
            ).strip(),
            "timestamp_unix": int(time.time()),
        }
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = (
            evidence_dir / f"e01b-fixture-api{api}-{receipt['timestamp_unix']}.json"
        )
        with destination.open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        destination.chmod(0o600)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=int, choices=(30, 33, 34, 36), required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, default=Path("artifacts/v3-e01"))
    args = parser.parse_args()
    outcome = verify_fixture(args.api, args.repo.resolve(), args.evidence_dir.resolve())
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"E01B_FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

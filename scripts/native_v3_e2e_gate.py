#!/usr/bin/env python3
"""E01.f evidence gate: four owned Android APK and fixture runs or fail closed.

The PASS here is *infrastructure only*, not an authenticated Android control
feature or independent production security certification.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scripts.native_v3_owned_avd import EXPECTED_NATIVE_ANDROID_TEST_NAMES

APIS = (30, 33, 34, 36)
SERIALS = {
    30: "emulator-5564",
    33: "emulator-5566",
    34: "emulator-5568",
    36: "emulator-5562",
}
BOOTHASH = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
DOC = "4ea8428c4dc75484e22c5832e3a564e1cc1c278cb4b1cb4fe87a3ac40d758fcf"
NATIVE_CHECKS = frozenset(("install", "http_status", "home_stops", "resume_starts"))
RGB = [[255, 64, 80], [21, 203, 131], [22, 137, 255]]


class GateError(ValueError):
    """An asserted Android gate prerequisite or real effect was not verified."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def _hex(value: Any, size: int) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(rf"[0-9a-f]{{{size}}}", value) is not None
    )


def _validate_pair(
    native: dict[str, Any], fixture: dict[str, Any], api: int, head: str, tree: str
) -> None:
    prefix = f"API {api}: "

    def need(condition: bool, why: str) -> None:
        _require(condition, prefix + why)

    serial = SERIALS[api]
    avd = f"android_mcp_native_v3_api{api}_20261014"
    need(native.get("api") == api and fixture.get("api") == api, "API mismatch")
    need(
        native.get("emulator") == serial and fixture.get("serial") == serial,
        "unexpected physical/shared serial",
    )
    need(
        native.get("avd") == avd and fixture.get("avd") == avd,
        "not an exclusively owned disposable AVD",
    )
    need(native.get("abi") == "arm64-v8a", "ABI mismatch")
    for item, length in (
        ("owner_attestation_nonce", 32),
        ("owner_attestation_sha256", 64),
        ("run_nonce", 32),
    ):
        source = native.get(item)
        witness = fixture.get(item)
        need(
            _hex(source, length) and source == witness,
            f"Owner signed attestation or run nonce mismatch: {item}",
        )
    pid = native.get("emulator_pid")
    need(
        isinstance(pid, int) and pid > 0 and fixture.get("emulator_pid") == pid,
        "emulator process identity changed",
    )
    boot = native.get("boot_identity")
    need(
        isinstance(boot, str)
        and BOOTHASH.fullmatch(boot) is not None
        and fixture.get("boot_identity") == boot,
        "boot epoch changed",
    )
    need(
        native.get("git_head") == head
        and fixture.get("git_head") == head
        and native.get("git_tree") == tree
        and fixture.get("git_tree") == tree,
        "source/head/tree mismatch",
    )
    need(
        native.get("run_type") == "V3_E01_BASELINE_NOT_PRODUCT_ACCEPTANCE"
        and native.get("n01_emulator_function_done") is False,
        "fake Native capability promotion",
    )
    need(
        native.get("instrumentation_tests") == 8
        and native.get("instrumentation_method_ids")
        == sorted(EXPECTED_NATIVE_ANDROID_TEST_NAMES)
        and _hex(native.get("apk_sha256"), 64)
        and _hex(native.get("instrumentation_apk_sha256"), 64),
        "missing real Native instrumentation APK evidence",
    )
    need(
        native.get("independent_android_oracle")
        == "PackageManager installed version/UID",
        "missing separate OS PackageManager proof",
    )
    need(
        native.get("forward_cleanup_verified") is True,
        "Native MCP forward was not verified clean after Stop/failure",
    )
    need(
        native.get("mcp_client") == "FastMCP to installed Native Android APK",
        "synthetic Kotlin JVM mistaken for actual Native APK",
    )
    mcp = native.get("mcp_check")
    need(isinstance(mcp, dict), "missing actual MCP results")
    need(
        mcp.get("result") == "pass"
        and mcp.get("registered_tools") == 1
        and mcp.get("physical_device_used") is False
        and mcp.get("environment") == "verified_emulator_only"
        and mcp.get("transport") == "adb_forward_to_local_mcp"
        and isinstance(mcp.get("checks"), list)
        and set(mcp["checks"]) == NATIVE_CHECKS
        and len(mcp["checks"]) == len(NATIVE_CHECKS),
        "actual Native APK MCP or negative/lifecycle path missing",
    )
    need(
        fixture.get("scope") == "E01.b TEST_FIXTURE_ONLY_NOT_NATIVE_FEATURE"
        and fixture.get("status") == "FIXTURE_READY"
        and fixture.get("product_case_passed") is False
        and fixture.get("actual_native_mcp_tool_used") is False,
        "fixture-only result forged as Native feature completion",
    )
    signatures = fixture.get("signing")
    need(isinstance(signatures, dict), "missing fixture signer evidence")
    need(
        all(
            _hex(signatures.get(item), 64)
            for item in (
                "fixture_sha256",
                "install_target_sha256",
                "fixture_certificate_sha256",
                "install_target_certificate_sha256",
            )
        ),
        "unverified test fixture APK/hash",
    )
    need(
        signatures["fixture_certificate_sha256"]
        == signatures["install_target_certificate_sha256"],
        "pinned test fixture signer mismatch",
    )
    need(
        _hex(fixture.get("androidTest_sha256"), 64)
        and fixture.get("document_bytes_sha256") == DOC,
        "missing deterministic fixture instrumentation/document",
    )
    need(
        fixture.get("instrumentation") == "12 real AndroidJUnitRunner tests",
        "mock or incomplete fixture AndroidJUnitRunner evidence",
    )
    before, after = (
        fixture.get("external_counter_before"),
        fixture.get("external_counter_after"),
    )
    need(
        isinstance(before, int)
        and not isinstance(before, bool)
        and 0 <= before < 10000000
        and type(after) is int
        and after == before + 1,
        "external gesture side effect missing",
    )
    need(
        fixture.get("counter_after_process_restart") == after,
        "persistent effect not observed after restart",
    )
    need(
        fixture.get("os_direct_document_denied") is True,
        "SAF unapproved read was not OS-denied",
    )
    need(
        _hex(fixture.get("independent_screenshot_sha256"), 64)
        and fixture.get("visual_colors") == RGB,
        "known-pixel fixture verification unavailable",
    )
    need(
        fixture.get("installer_target")
        == "signed APK validated, NOT installed by Native PackageInstaller",
        "fixture setup incorrectly claims Native install execution",
    )


def evaluate_matrix(
    receipts: list[tuple[dict[str, Any], dict[str, Any]]],
    head: str,
    tree: str,
) -> dict[str, Any]:
    """Pure admission; caller must actually run both Android subprocesses."""
    _require(_hex(head, 40) and _hex(tree, 40), "Unpinned Git source")
    _require(len(receipts) == len(APIS), "Must check all four distinct Android APIs")
    api_ids: list[int] = []
    for native, fixture in receipts:
        _require(
            isinstance(native, dict) and isinstance(fixture, dict),
            "Invalid paired Android receipts",
        )
        api = native.get("api")
        _require(type(api) is int and api in APIS, "Invalid Android API")
        _require(api not in api_ids, "Duplicate Android API result")
        _validate_pair(native, fixture, api, head, tree)
        api_ids.append(api)
    _require(set(api_ids) == set(APIS), "Required Android API missing")
    for key in ("owner_attestation_nonce", "run_nonce"):
        _require(
            len({pair[0][key] for pair in receipts}) == len(APIS),
            f"Test-only {key} was reused across different emulator boots",
        )
    for key, group in (
        ("apk_sha256", [pair[0] for pair in receipts]),
        ("instrumentation_apk_sha256", [pair[0] for pair in receipts]),
        ("androidTest_sha256", [pair[1] for pair in receipts]),
    ):
        _require(
            len({row[key] for row in group}) == 1, key + " drift across Android API"
        )
    for key in (
        "fixture_sha256",
        "fixture_certificate_sha256",
        "install_target_sha256",
        "install_target_certificate_sha256",
    ):
        _require(
            len({pair[1]["signing"][key] for pair in receipts}) == 1,
            key + " not pinned across emulator matrix",
        )
    return {
        "status": "PASS_E01_INFRASTRUCTURE_ONLY",
        "product_status": "PRODUCT_INCOMPLETE",
        "verified_api_levels": sorted(api_ids),
        "git_head": head,
        "git_tree": tree,
        "android_junit_tests": sum(8 + 12 for _ in receipts),
        "native_mcp_client_calls_verified": len(receipts),
        "fixture_is_not_native_executor": True,
        "native_product_features_done": 0,
        "new_v3_feature_cases_certified": 0,
        "evidence_class": "REPEATED_LIVE_AVD_RUNS_NOT_INDEPENDENT_SIGNED_RELEASE_PROOF",
    }


def _run(argv: list[str], max_seconds: int = 180) -> str:
    try:
        result = subprocess.run(
            argv, capture_output=True, timeout=max_seconds, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(
            "Required native Android subprocess unavailable/timed out"
        ) from exc
    if len(result.stdout) + len(result.stderr) > 160 * 1024:
        raise GateError("Android subprocess exceeded safe output bound")
    if result.returncode:
        error = result.stderr.decode("utf-8", "replace")
        raise GateError(
            f"Android test subprocess failure: {Path(argv[0]).name}: {error[:700]}"
        )
    return result.stdout.decode("utf-8", "replace")


def run_matrix(repo: Path, python: Path, evidence_dir: Path) -> dict[str, Any]:
    """Execute app-on-device (not standalone JVM), fixture and external oracle."""
    repo = repo.resolve(strict=True)
    python = python.absolute()
    _require(
        repo.joinpath("android/gradlew").is_file()
        and python.is_file()
        and python.stat().st_mode & 0o100 != 0,
        "Pinned source/working Python client missing",
    )
    # Changes may be tested during development, but only a clean tree is
    # eligible for a merge-gate receipt proving the tested SHA/tree.
    _require(
        not _run(["git", "-C", str(repo), "status", "--porcelain"]).strip(),
        "Source must be committed and clean before exact-SHA E01.f gate",
    )
    head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip()
    tree = _run(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]).strip()
    evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    native_apk = repo / "android/app/build/outputs/apk/debug/app-debug.apk"
    native_tests = (
        repo / "android/app/build/outputs/apk/androidTest/debug/"
        "app-debug-androidTest.apk"
    )
    _require(
        all(path.is_file() for path in (native_apk, native_tests)),
        "Must build actual installed Native/AndroidTest APKs first",
    )
    pair_results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for api in APIS:
        run_nonce = secrets.token_hex(16)
        native = json.loads(
            _run(
                [
                    str(python),
                    "-m",
                    "scripts.native_v3_owned_avd",
                    "--api",
                    str(api),
                    "--repo",
                    str(repo),
                    "--python",
                    str(python),
                    "--apk",
                    str(native_apk),
                    "--instrumentation-apk",
                    str(native_tests),
                    "--evidence-dir",
                    str(evidence_dir),
                    "--run-nonce",
                    run_nonce,
                ]
            )
        )
        fixture = json.loads(
            _run(
                [
                    str(python),
                    "-m",
                    "scripts.native_v3_fixture_matrix",
                    "--api",
                    str(api),
                    "--repo",
                    str(repo),
                    "--evidence-dir",
                    str(evidence_dir),
                    "--run-nonce",
                    run_nonce,
                ]
            )
        )
        _require(
            native.get("run_nonce") == run_nonce
            and fixture.get("run_nonce") == run_nonce,
            "Child process did not answer this exact fresh test-run challenge",
        )
        pair_results.append((native, fixture))
        # Fail at first version with missing genuine evidence, not only after
        # collecting all fake successes.
        _validate_pair(native, fixture, api, head, tree)
    result = evaluate_matrix(pair_results, head, tree)
    result["timestamp_unix"] = int(time.time())
    output_path = (
        evidence_dir / f"e01f-four-api-gate-{head[:12]}-{result['timestamp_unix']}.json"
    )
    with output_path.open("x", encoding="utf-8") as target:
        json.dump(result, target, indent=2, sort_keys=True)
        target.write("\n")
    output_path.chmod(0o600)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_matrix(args.repo, args.python, args.evidence_dir), sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GateError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"E01F_FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

#!/usr/bin/env python3
"""Offline consistency gate for the 20 Native capability families and 38 merges.

The ledger records *safe roadmap disposition*, never 20 live Android Tools.
Pass --strict-git to verify every merge receipt against local Git history.
No network, ADB, Android mutation, file write or external process shell.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/native-capability-ledger.v1.json"
PLAN = ROOT / "docs/native-mcp-implementation-plan-20261013.md"
MATRIX = ROOT / "docs/native-mcp-serial-test-cases-20261013.md"
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
PACKAGE_RX = re.compile(r"N[0-8]\.[a-z]\Z")
SHA_RX = re.compile(r"[a-f0-9]{40}\Z")
ALLOWED = {
    "merged_verified",
    "inert_merged",
    "plan_only",
    "blocked",
    "unsupported_by_platform",
}
ANDROID = "{http://schemas.android.com/apk/res/android}"


class LedgerError(ValueError):
    """The proposed ledger contradicts the specified roadmap or safe APK."""


def require(test: bool, why: str) -> None:
    if not test:
        raise LedgerError(why)


def verify_ledger(path: Path = LEDGER, strict_git: bool = False) -> dict[str, int]:
    content: dict[str, Any] = json.loads(path.read_text())
    require(content.get("schema_version") == 1, "Unknown ledger schema")
    require(
        content.get("production_public_native_tools") == ["device_status"],
        "Unexpected public Native Tool catalog",
    )
    require(
        content.get("specified_test_case_ids_are_not_an_executed_test_count") is True,
        "Specified cases must not be advertised as executed tests",
    )
    require(
        isinstance(content.get("snapshot_main_sha"), str)
        and SHA_RX.fullmatch(content["snapshot_main_sha"]) is not None,
        "Malformed integration snapshot SHA",
    )

    specs = PLAN.read_text()
    packages = re.findall(
        r"^\|\s*\d\d\s*\|\s*\*\*(N[0-8]\.[a-z])\*\*", specs, re.MULTILINE
    )
    require(
        len(packages) == len(set(packages)) == 38,
        "Roadmap IDs are not 38 unique packages",
    )
    documented_cases = re.findall(
        r"\*\*(T-N[0-8][A-Z]-0[1-6]):\*\*", MATRIX.read_text()
    )
    require(
        len(documented_cases) == len(set(documented_cases)) == 228,
        "Test specification must be 228 unique case IDs",
    )
    expected_cases = {
        f"T-{package.replace('.', '').upper()}-{n:02d}"
        for package in packages
        for n in range(1, 7)
    }
    require(
        set(documented_cases) == expected_cases,
        "Missing or duplicate six-case package matrix",
    )
    require(
        content.get("roadmap_packages_merged") == len(packages)
        and content.get("specified_test_case_ids") == len(documented_cases),
        "Roadmap or numbered-case totals inconsistent",
    )

    capabilities = content.get("capabilities")
    require(
        isinstance(capabilities, list) and len(capabilities) == 20,
        "Exactly N01 through N20 are required",
    )
    ids = [item.get("id") for item in capabilities if isinstance(item, dict)]
    require(
        ids == [f"N{i:02d}" for i in range(1, 21)],
        "Capabilities must appear exactly once in N01-N20 order",
    )
    found_packages: set[str] = set()
    receipts: dict[str, tuple[int, str]] = {}
    for item in capabilities:
        cid = item["id"]
        for field in (
            "name",
            "source_file",
            "android_api_or_boundary",
            "required_permission_or_review_gate",
            "verified_scope",
        ):
            require(
                isinstance(item.get(field), str) and bool(item[field].strip()),
                f"{cid}: empty required evidence {field}",
            )
        require(item.get("status") in ALLOWED, f"{cid}: unknown status")
        required_active = cid in {"N01", "N16"}
        require(
            item.get("feature_executable_in_production") is required_active,
            f"{cid}: capability may falsely claim production execution",
        )
        require(
            (item["status"] == "merged_verified") is required_active,
            f"{cid}: emulator/status feature status overstated",
        )
        require(
            item.get("public_native_tool")
            == ("device_status" if cid == "N01" else None),
            f"{cid}: unpublished sensitive Tool must remain absent",
        )
        source = Path(item["source_file"])
        require(
            not source.is_absolute() and ".." not in source.parts,
            f"{cid}: source path escapes repository",
        )
        require((ROOT / source).is_file(), f"{cid}: missing provider source")
        own_packages = item.get("work_packages")
        own_receipts = item.get("merge_receipts")
        require(
            isinstance(own_packages, list)
            and bool(own_packages)
            and len(own_packages) == len(set(own_packages)),
            f"{cid}: invalid package assignments",
        )
        require(
            isinstance(own_receipts, list) and len(own_receipts) == len(own_packages),
            f"{cid}: missing PR / SHA receipts",
        )
        for package, receipt in zip(own_packages, own_receipts, strict=True):
            require(
                isinstance(package, str)
                and PACKAGE_RX.fullmatch(package) is not None
                and package in packages,
                f"{cid}: unknown work package",
            )
            found_packages.add(package)
            require(
                isinstance(receipt, dict) and receipt.get("package") == package,
                f"{cid}: receipts out of package order",
            )
            pr = receipt.get("pr")
            sha = receipt.get("merge_sha")
            require(
                isinstance(pr, int)
                and pr > 0
                and isinstance(sha, str)
                and SHA_RX.fullmatch(sha) is not None,
                f"{cid}: missing PR or invalid full merge SHA",
            )
            if package in receipts:
                require(
                    receipts[package] == (pr, sha),
                    f"{cid}: inconsistent merge receipts for {package}",
                )
            else:
                receipts[package] = (pr, sha)
    require(
        found_packages == set(packages), "A Native work package has no N01-N20 coverage"
    )

    gateway = GATEWAY.read_text()
    require(
        gateway.count("server.addTool(") == 1 and 'name = "device_status"' in gateway,
        "Actual Kotlin APK catalog not status-only",
    )
    manifest = ET.parse(MANIFEST).getroot()
    perms = {node.get(ANDROID + "name") for node in manifest.findall("uses-permission")}
    require(
        perms
        == {
            "android.permission.INTERNET",
            "android.permission.FOREGROUND_SERVICE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
            "android.permission.POST_NOTIFICATIONS",
        },
        "APK Android permission allowlist expanded",
    )
    require(
        not manifest.findall(".//receiver"), "Unexpected receiver or boot/admin path"
    )

    if strict_git:
        for package, (pr, sha) in receipts.items():
            history = subprocess.run(
                ["git", "-C", str(ROOT), "show", "-s", "--format=%s", sha],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            require(
                package.lower() in history.lower() and f"(#{pr})" in history,
                f"{package}: PR and commit subject mismatch",
            )
            ancestor = subprocess.run(
                ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", sha, "HEAD"],
                check=False,
                capture_output=True,
            )
            require(
                ancestor.returncode == 0, f"{package}: merge not in current checkout"
            )
        require(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "merge-base",
                    "--is-ancestor",
                    content["snapshot_main_sha"],
                    "HEAD",
                ],
                check=False,
                capture_output=True,
            ).returncode
            == 0,
            "Snapshot main is not an ancestor of checkout",
        )

    return {
        "capabilities": len(capabilities),
        "merged_packages": len(receipts),
        "specified_case_ids": len(documented_cases),
        "sensitive_live_tools": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--strict-git", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_ledger(args.ledger, args.strict_git)
    except (
        LedgerError,
        KeyError,
        TypeError,
        OSError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        print(json.dumps({"result": "fail", "reason": str(error)}))
        return 2
    print(json.dumps({"result": "pass", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

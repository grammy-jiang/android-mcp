#!/usr/bin/env python3
"""V3 baseline and independently witnessed E2E admission.

This validator never generates its own Android evidence. An independent,
pinned Ed25519 oracle may attest a canonical result, but signing test data
does not prove a device was operated. Release review is a separate gate.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

CAPABILITIES = frozenset(f"N{n:02d}" for n in range(1, 21))
API_LEVELS = frozenset({30, 33, 34, 36})
RECEIPT_FIELDS = frozenset(
    {
        "case_id",
        "layer",
        "executor",
        "origin",
        "api",
        "avd_identity",
        "boot_identity",
        "git_sha",
        "git_tree",
        "apk_sha256",
        "fixture_sha256",
        "mcp_request",
        "mcp_response",
        "authenticated_principal",
        "android_api_callback",
        "os_oracle",
        "negative_recovery",
        "cleanup",
    }
)


def _require(condition: bool, why: str) -> None:
    if not condition:
        raise ValueError(why)


def _hex_digest(text: Any, length: int) -> bool:
    return isinstance(text, str) and bool(re.fullmatch(f"[0-9a-f]{{{length}}}", text))


def _is_real_test_id(test_id: str) -> bool:
    return bool(
        re.fullmatch(
            r"V3-(?:N(?:0[1-9]|1[0-9]|20)-0[1-8]|XR-(?:0[1-9]|[12][0-9]|3[012]))",
            test_id,
        )
    )


def audit_baseline(
    registry: dict[str, Any], traceability: Path, plan: Path
) -> dict[str, Any]:
    """Fail on missing cases, aliases, fictitious passes and wrong counts.

    Truthful baseline NOT_RUN is acceptable, but not itself feature progress.
    """
    families = registry.get("capability_families")
    _require(
        isinstance(families, list) and len(families) == 20,
        "Expected 20 capability families",
    )
    family_ids = [family["capability_id"] for family in families]
    _require(
        set(family_ids) == CAPABILITIES and len(set(family_ids)) == 20,
        "Duplicate/missing family ID",
    )
    ids: list[str] = []
    for family in families:
        family_id = family["capability_id"]
        tests = family.get("tests", [])
        _require(len(tests) == 8, f"{family_id}: exactly eight new cases")
        _require(
            family.get("feature_acceptance_status")
            in {"NOT_VERIFIED_V3", "NOT_DONE", "BLOCKED_EXTERNAL"},
            f"{family_id}: feature done cannot be self-certified by specification",
        )
        for i, case in enumerate(tests, 1):
            _require(
                case.get("test_id") == f"V3-{family_id}-{i:02d}",
                "Missing/duplicate case id",
            )
            _require(
                case.get("status") == "NOT_RUN",
                "Specification status is not executed evidence",
            )
            ids.append(case["test_id"])
    crosscut = registry.get("crosscut_cases")
    _require(
        isinstance(crosscut, list) and len(crosscut) == 32,
        "Expected 32 cross-cutting cases",
    )
    for i, case in enumerate(crosscut, 1):
        _require(case.get("test_id") == f"V3-XR-{i:02d}", "Missing/duplicate crosscut")
        _require(
            case.get("status") == "NOT_RUN", "Crosscut cannot claim unverified pass"
        )
        ids.append(case["test_id"])
    _require(
        len(ids) == 192 and len(set(ids)) == 192 and all(map(_is_real_test_id, ids)),
        "Invalid V3 case inventory",
    )
    with traceability.open(newline="", encoding="utf-8") as source:
        legacy = list(csv.DictReader(source))
    _require(len(legacy) == 228, "Expected 228 historical case rows")
    legacy_ids = [row.get("legacy_case_id", "") for row in legacy]
    _require(len(set(legacy_ids)) == 228, "Duplicate historical case IDs")
    _require(
        all(re.fullmatch(r"T-N[0-8][A-F]-0[1-6]", item) for item in legacy_ids),
        "Malformed historical specification ID",
    )
    by_package: dict[str, set[str]] = {}
    for row in legacy:
        pkg = row.get("legacy_work_package", "")
        by_package.setdefault(pkg, set()).add(row["legacy_case_id"])
        _require(
            row.get("execution_state") in {"NOT_RUN_V3", "NOT_VERIFIED_V3"},
            "False legacy execution pass",
        )
    _require(
        len(by_package) == 38 and all(len(items) == 6 for items in by_package.values()),
        "Historical six cases per 38 work packages missing",
    )
    plan_text = plan.read_text(encoding="utf-8")
    packages = re.findall(r"\*\*(E\d\d\.[a-z]) — ", plan_text)
    _require(
        len(packages) == 70 and len(set(packages)) == 70,
        "Missing/duplicated V3 work package",
    )
    _require(
        {f"E{i:02}" for i in range(16)} == {p.split(".")[0] for p in packages},
        "Missing V3 implementation stage",
    )
    return {
        "capabilities": len(families),
        "v3_cases": len(ids),
        "historical_cases": len(legacy),
        "packages": len(packages),
        "emulator_features_done": 0,
        "production_features_done": 0,
        "verified_legacy_tests": sum(
            row.get("legacy_existing_test_name_verified", "").startswith("VERIFIED:")
            for row in legacy
        ),
        "status": "PRODUCT_INCOMPLETE",
    }


def _valid_receipt_fields(receipt: dict[str, Any]) -> bool:
    if not RECEIPT_FIELDS.issubset(receipt):
        return False
    if not _is_real_test_id(receipt["case_id"]):
        return False
    if receipt["layer"] != "PASS_REAL_E2E":
        return False
    if receipt["executor"] != "NATIVE_APK" or receipt["origin"] != "ANDROID_FRAMEWORK":
        return False
    if receipt["api"] not in API_LEVELS:
        return False
    if not all(_hex_digest(receipt[k], 40) for k in ("git_sha", "git_tree")):
        return False
    if not all(_hex_digest(receipt[k], 64) for k in ("apk_sha256", "fixture_sha256")):
        return False
    if not all(
        isinstance(receipt[k], dict) and receipt[k]
        for k in (
            "avd_identity",
            "boot_identity",
            "mcp_request",
            "mcp_response",
            "authenticated_principal",
            "android_api_callback",
            "negative_recovery",
            "cleanup",
        )
    ):
        return False
    if receipt["cleanup"].get("released") is not True:
        return False
    oracle = receipt["os_oracle"]
    if not isinstance(oracle, dict):
        return False
    if oracle.get("observed") is not True or oracle.get("native_causality") is not True:
        return False
    if oracle.get("observer_process") in (
        None,
        "",
        receipt["android_api_callback"].get("process"),
    ):
        return False
    return oracle.get("actor") != receipt["authenticated_principal"].get("actor")


def admit_emulator_case(receipt: dict[str, Any], trust_roots: dict[str, bytes]) -> bool:
    """Trust only complete real-path receipts independently signed and pinned.

    trust_roots maps an externally provisioned key ID to the Ed25519 *public*
    key's raw 32 bytes. There is NO built-in root, test-key or bypass flag.
    This is a single-case policy proof; no single case can close a family.
    """
    if not isinstance(receipt, dict) or not _valid_receipt_fields(receipt):
        return False
    oracle = receipt["os_oracle"]
    key_id = oracle.get("key_id")
    signature = oracle.get("signature")
    public_key = trust_roots.get(key_id) if isinstance(key_id, str) else None
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        return False
    if not _hex_digest(signature, 128):
        return False
    # Do not sign a second mutable interpretation of the receipt. Canonical
    # JSON signs all receipt fields except the detached signature.
    canonical = json.loads(json.dumps(receipt))
    canonical["os_oracle"].pop("signature")
    message = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(signature), message
        )
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Native V3 non-self-certifying admission checker"
    )
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--traceability", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    options = parser.parse_args()
    registry = json.loads(options.registry.read_text(encoding="utf-8"))
    print(
        json.dumps(
            audit_baseline(registry, options.traceability, options.plan), sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

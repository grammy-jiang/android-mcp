#!/usr/bin/env python3
"""E00.d reviewed *rules*, not a runtime user-grant or review approval.

Rejects invalid/missing risk owners, platform unsupported escalations and
model-supplied authority. A positive policy-plan verdict is deliberately NOT
an operational grant or Native MCP implementation.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

IDS = frozenset(f"N{idx:02d}" for idx in range(1, 21))
CORE = frozenset({"N01", "N02", "N03", "N04", "N05", "N06", "N14", "N16"})
REQUIRES_OS_CONSENT = frozenset({"N07", "N08", "N09", "N10", "N11", "N13", "N15"})
CONTROL = frozenset({"N08", "N12", "N15", "N18"})
REQUIRED_SHORTCUT_DENIALS = frozenset(
    {
        "ADB_SUBSTITUTES_NATIVE_EFFECT",
        "SIMULATED_ANDROID_GRANT",
        "MODEL_SELF_AUTHORIZATION",
        "UNREVIEWED_PHYSICAL_TARGET",
    }
)
PROFILE_MAP = {
    "CORE": frozenset({"S0_STATUS_ONLY", "S1_PAIRED_READ"}),
    "SENSITIVE_USER_CONSENT": frozenset(
        {"S2_USER_CONSENTED_READ", "S3_APPROVED_CONTROL"}
    ),
    "AUTHORIZED_WRITE": frozenset({"S3_APPROVED_CONTROL"}),
    "OPTIONAL_CONSENT": frozenset({"S2_USER_CONSENTED_READ"}),
    "SECURITY_FOUNDATION": frozenset({"S1_PAIRED_READ", "S3_APPROVED_CONTROL"}),
    "MANAGED_PROFILE_OPTIONAL": frozenset({"EXTERNAL_MANAGED_LAB"}),
    "HOST_FALLBACK_PLATFORM_LIMIT": frozenset({"UNSUPPORTED_APK_HOST_FALLBACK"}),
}


def _require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def validate_authority_matrix(
    matrix: dict[str, Any], registry: dict[str, Any]
) -> dict[str, Any]:
    _require(
        matrix.get("schema") == "native-v3-authority-risk.v1",
        "Unknown authority schema",
    )
    _require(
        matrix.get("release_status") == "PRODUCT_INCOMPLETE"
        and matrix.get("no_external_approvals_assumed") is True,
        "Source cannot assume approval or certify product",
    )
    items = matrix.get("capabilities")
    _require(isinstance(items, list) and len(items) == 20, "All 20 families mandatory")
    ids = [row.get("id") for row in items]
    _require(set(ids) == IDS and len(set(ids)) == 20, "Duplicate or missing capability")
    reg_rows = registry.get("capability_families", [])
    _require(len(reg_rows) == 20, "Wrong source acceptance registry")
    families = {row["capability_id"]: row for row in reg_rows}
    _require(set(families) == IDS, "Registry coverage drift")

    for row in items:
        cap = row["id"]
        ref = families[cap]
        profile = row.get("profile")
        _require(
            profile in PROFILE_MAP[ref["target_scope"]],
            f"{cap}: profile conflicts with approved scope",
        )
        _require(
            row.get("release_status") == "NOT_DONE",
            f"{cap}: no external product signoff",
        )
        _require(
            row.get("required_scope")
            in {
                "status",
                "read",
                "user_consented",
                "approved_control",
                "managed_lab",
                "host_maintenance",
            },
            f"{cap}: scope missing",
        )
        owners = row.get("owner_roles")
        _require(
            isinstance(owners, dict)
            and all(
                isinstance(owners.get(x), str) and len(owners[x]) >= 8
                for x in (
                    "risk_owner",
                    "host_operator",
                    "android_user",
                    "independent_reviewer",
                )
            ),
            f"{cap}: accountable roles incomplete",
        )
        review = row.get("independent_review")
        _require(
            isinstance(review, dict)
            and review.get("status") == "PENDING_EXTERNAL"
            and review.get("owner_role") == owners["independent_reviewer"]
            and review.get("owner_role") != owners["risk_owner"],
            f"{cap}: independent security signoff cannot be self asserted",
        )
        _require(
            row.get("physical_device_access") == "DENIED_UNLESS_SEPARATELY_APPROVED",
            f"{cap}: unjustified real-device access",
        )
        _require(
            isinstance(row.get("android_os_mechanism"), str)
            and bool(re.fullmatch(r"[A-Z0-9_]{12,128}", row["android_os_mechanism"])),
            f"{cap}: missing concrete Android API",
        )
        _require(
            set(row.get("prohibited_shortcuts", [])) == REQUIRED_SHORTCUT_DENIALS,
            f"{cap}: missing mandatory authority boundary",
        )
        _require(
            type(row.get("android_consent_required")) is bool
            and type(row.get("operator_approval_required")) is bool
            and type(row.get("native_lease_required")) is bool,
            f"{cap}: authority flags not explicitly classified",
        )
        _require(
            row["android_consent_required"]
            == (cap in REQUIRES_OS_CONSENT or cap == "N19"),
            f"{cap}: real Android OS consent mechanism misclassified",
        )
        _require(
            row["native_lease_required"] == (cap in CONTROL or cap == "N19"),
            f"{cap}: write/managed native fence cannot be optional",
        )
        if cap in CONTROL or cap in {"N17", "N19", "N20"}:
            _require(
                row["operator_approval_required"], f"{cap}: operator approval omitted"
            )
        if cap in CORE:
            _require(
                not row["android_consent_required"]
                and not row["native_lease_required"],
                f"{cap}: core status/read must not claim magic OS grant",
            )
        if cap == "N12":
            _require(
                row["android_os_mechanism"] == "EXPLICIT_EXPORTED_INTENT_LAUNCH"
                and not row["android_consent_required"],
                "An ordinary explicit launch does NOT invent an Android OS consent dialog",
            )
        if cap in {"N07", "N08"}:
            _require(
                "ACCESSIBILITY_" in row["android_os_mechanism"],
                f"{cap}: must require genuine Settings-enabled service",
            )
        if cap in {"N09", "N10"}:
            _require(
                row["android_os_mechanism"].startswith("MEDIAPROJECTION_"),
                f"{cap}: real MediaProjection callback required",
            )
        if cap == "N11":
            _require("SAF_" in row["android_os_mechanism"], "No storage-wide grant")
            conditional = row.get("conditional_authority")
            _require(
                isinstance(conditional, list)
                and len(conditional) == 2
                and {item.get("operation") for item in conditional}
                == {"create_document", "export_document"}
                and all(
                    item.get("operator_approval_required") is True
                    and item.get("native_lease_required") is True
                    for item in conditional
                ),
                "SAF write operations require separately signed action and Native lease",
            )
        if cap == "N15":
            _require(
                "PACKAGEINSTALLER_PENDING_USER_ACTION" == row["android_os_mechanism"],
                "Silent Android package installation is not authorized",
            )
        if cap == "N16":
            _require(
                row.get("required_scope") == "status",
                "Local user Stop must remain available unpaired in Native UI",
            )
        if cap == "N17":
            _require(
                "KEYSTORE_" in row["android_os_mechanism"],
                "Host identity cannot come from adb/localhost/Origin",
            )
        if cap == "N19":
            _require(
                row.get("runtime") == "MANAGED_DPC_TEST_AVD_ONLY"
                and row.get("test_environment") == "DEDICATED_MANAGED_TEST_AVD_ONLY"
                and row.get("fallback") == "BLOCKED_EXTERNAL_DEDICATED_MANAGED_LAB",
                "DeviceOwner cannot silently deploy to ordinary Android app",
            )
        elif cap == "N20":
            _require(
                row.get("runtime") == "HOST_READ_ONLY_MANUAL_FALLBACK"
                and row.get("fallback")
                == "HOST_READ_ONLY_DIAGNOSTICS_MANUAL_OWNER_RUNBOOK",
                "Root/ROM/Bootloader unsupported by ordinary APK",
            )
        else:
            _require(
                row.get("runtime") in {"NATIVE_ANDROID", "NATIVE_ANDROID_AND_HOST"},
                f"{cap}: unexpected platform/runtime",
            )
    return {
        "capability_count": 20,
        "product_ready": 0,
        "external_review_pending": 20,
        "platform_exclusion_n20": "NATIVE_UNSUPPORTED_HOST_READ_ONLY",
        "managed_n19": "DEDICATED_MANAGED_TEST_AVD_ONLY",
        "android_os_consent_required": len(REQUIRES_OS_CONSENT) + 1,
        "control_profiles": len(CONTROL),
        "result": "VALID_POLICY_CLASSIFICATION_NOT_PRODUCT_GRANT",
    }


def decide_request(
    matrix: dict[str, Any], capability_id: str, request: dict[str, Any]
) -> str:
    """Fail closed planning oracle, NEVER a Native privileged token issuer.

    Positive result means only that the proposed request is not excluded by
    this static matrix; production must independently verify cryptographic
    identity, actual OS callback and latest Native arbiter before any effect.
    """
    rows = {row["id"]: row for row in matrix["capabilities"]}
    if capability_id not in rows:
        return "DENY_UNKNOWN_CAPABILITY"
    policy = rows[capability_id]
    if capability_id == "N01":
        return (
            "PLAN_ONLY_NOT_LIVE_APPROVAL"
            if request.get("scope") == "status"
            else "DENY_SCOPE"
        )
    if request.get("host_authenticated") is not True:
        return "DENY_UNAUTHENTICATED"
    if request.get("physical_target") is True:
        return "DENY_PHYSICAL_TARGET"
    if capability_id == "N20":
        return "DENY_PLATFORM_UNSUPPORTED"
    if capability_id == "N19":
        return "DENY_EXTERNAL_MANAGED_GATE"
    if request.get("scope") != policy["required_scope"]:
        return "DENY_SCOPE"
    if (
        policy["android_consent_required"]
        and request.get("android_os_consent") is not True
    ):
        return "DENY_OS_CONSENT"
    # A user-picked SAF URI is permission to a document, not blanket authority
    # for a remote caller to write. A separate signed operator action and
    # authoritative Native lease are required for CREATE/EXPORT operations.
    saf_write = capability_id == "N11" and request.get("operation") in {
        "create_document",
        "export_document",
    }
    if capability_id == "N11" and request.get("operation", "open_document") not in {
        "open_document",
        "create_document",
        "export_document",
    }:
        return "DENY_OPERATION"
    if (policy["operator_approval_required"] or saf_write) and request.get(
        "operator_approval"
    ) is not True:
        return "DENY_OPERATOR_APPROVAL"
    if (policy["native_lease_required"] or saf_write) and request.get(
        "native_lease"
    ) is not True:
        return "DENY_NATIVE_LEASE"
    if request.get("independent_security_approved") is not True:
        return "DENY_INDEPENDENT_REVIEW"
    if (
        policy["android_consent_required"]
        and request.get("android_grant_evidence") != "ANDROID_FRAMEWORK_CALLBACK"
    ):
        return "DENY_UNVERIFIED_OS_GRANT"
    if (
        capability_id in {"N08", "N12", "N15"}
        and request.get("target_is_owned_fixture") is not True
    ):
        return "DENY_UNVERIFIED_TARGET"
    return "PLAN_ONLY_NOT_LIVE_APPROVAL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()
    risk = json.loads(args.matrix.read_text())
    registry = json.loads(args.registry.read_text())
    print(json.dumps(validate_authority_matrix(risk, registry), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

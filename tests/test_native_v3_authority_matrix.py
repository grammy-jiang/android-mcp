"""Adversarial E00.d scope-approval and per-Android capability risk matrix."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.native_v3_authority_matrix import (
    decide_request,
    validate_authority_matrix,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/native-v3/v3-authority-risk-register.json"
REG = (
    ROOT
    / "docs/native-v3/Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json"
)


class NativeV3AuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.registry = json.loads(REG.read_text(encoding="utf-8"))

    def test_every_capability_has_specific_os_authority_risk_and_owner(self) -> None:
        result = validate_authority_matrix(self.matrix, self.registry)
        self.assertEqual(result["capability_count"], 20)
        self.assertEqual(result["product_ready"], 0)
        self.assertEqual(result["external_review_pending"], 20)
        self.assertEqual(
            result["platform_exclusion_n20"], "NATIVE_UNSUPPORTED_HOST_READ_ONLY"
        )
        self.assertEqual(result["managed_n19"], "DEDICATED_MANAGED_TEST_AVD_ONLY")

    def test_dropped_or_duplicate_capability_fails(self) -> None:
        for forged in (
            {**self.matrix, "capabilities": self.matrix["capabilities"][:-1]},
            {
                **self.matrix,
                "capabilities": self.matrix["capabilities"][:-1]
                + [copy.deepcopy(self.matrix["capabilities"][0])],
            },
        ):
            with self.assertRaises(ValueError):
                validate_authority_matrix(forged, self.registry)

    def test_legacy_unauthenticated_localhost_cannot_acquire_any_read(self) -> None:
        for n in range(2, 21):
            cap = f"N{n:02d}"
            self.assertEqual(
                decide_request(
                    self.matrix,
                    cap,
                    {
                        "host_authenticated": False,
                        "scope": "read",
                        "android_os_consent": True,
                        "operator_approval": True,
                        "independent_security_approved": True,
                        "native_lease": True,
                    },
                ),
                "DENY_UNAUTHENTICATED",
                cap,
            )

    def test_system_prompt_grant_never_implied_by_model_claim(self) -> None:
        for cap in ("N07", "N08", "N09", "N10", "N11", "N13", "N15"):
            control = cap in ("N08", "N15")
            self.assertEqual(
                decide_request(
                    self.matrix,
                    cap,
                    {
                        "host_authenticated": True,
                        "scope": "approved_control" if control else "user_consented",
                        "android_os_consent": False,
                        "operator_approval": True,
                        "independent_security_approved": True,
                        "native_lease": True,
                    },
                ),
                "DENY_OS_CONSENT",
                cap,
            )

    def test_approved_control_requires_native_lease_operator_and_review(self) -> None:
        for cap in ("N08", "N12", "N15"):
            base = {
                "host_authenticated": True,
                "scope": "approved_control",
                "android_os_consent": True,
                "operator_approval": True,
                "independent_security_approved": True,
                "native_lease": True,
                "target_is_owned_fixture": True,
            }
            for missing, denial in (
                ("operator_approval", "DENY_OPERATOR_APPROVAL"),
                ("native_lease", "DENY_NATIVE_LEASE"),
                ("independent_security_approved", "DENY_INDEPENDENT_REVIEW"),
            ):
                forged = {**base, missing: False}
                with self.subTest(cap=cap, field=missing):
                    self.assertEqual(decide_request(self.matrix, cap, forged), denial)

    def test_root_or_flash_never_allowed_by_native(self) -> None:
        allowed = {
            "host_authenticated": True,
            "scope": "approved_control",
            "android_os_consent": True,
            "operator_approval": True,
            "independent_security_approved": True,
            "native_lease": True,
            "target_is_owned_fixture": True,
            "managed_lab_authorized": True,
        }
        self.assertEqual(
            decide_request(self.matrix, "N20", allowed), "DENY_PLATFORM_UNSUPPORTED"
        )
        self.assertEqual(
            decide_request(self.matrix, "N19", allowed), "DENY_EXTERNAL_MANAGED_GATE"
        )

    def test_read_profile_requires_exact_versioned_scope(self) -> None:
        request = {
            "host_authenticated": True,
            "scope": "status",
            "android_os_consent": False,
            "operator_approval": False,
            "independent_security_approved": True,
            "native_lease": False,
        }
        self.assertEqual(decide_request(self.matrix, "N02", request), "DENY_SCOPE")
        self.assertEqual(
            decide_request(self.matrix, "N01", request), "PLAN_ONLY_NOT_LIVE_APPROVAL"
        )

    def test_mock_grant_or_physical_target_cannot_upgrade(self) -> None:
        request = {
            "host_authenticated": True,
            "scope": "approved_control",
            "android_os_consent": True,
            "operator_approval": True,
            "independent_security_approved": True,
            "native_lease": True,
            "target_is_owned_fixture": True,
            "android_grant_evidence": "SIMULATED",
        }
        self.assertEqual(
            decide_request(self.matrix, "N15", request), "DENY_UNVERIFIED_OS_GRANT"
        )
        request["android_grant_evidence"] = "ANDROID_FRAMEWORK_CALLBACK"
        request["physical_target"] = True
        self.assertEqual(
            decide_request(self.matrix, "N15", request), "DENY_PHYSICAL_TARGET"
        )

    def test_unsafe_registry_override_cannot_self_approve_security(self) -> None:
        data = copy.deepcopy(self.matrix)
        target = next(item for item in data["capabilities"] if item["id"] == "N17")
        target["independent_review"]["status"] = "APPROVED"
        with self.assertRaises(ValueError):
            validate_authority_matrix(data, self.registry)

    def test_all_safety_profiles_are_exactly_bound_to_registry(self) -> None:
        data = copy.deepcopy(self.matrix)
        target = next(item for item in data["capabilities"] if item["id"] == "N20")
        target["runtime"] = "NATIVE_ANDROID"
        with self.assertRaises(ValueError):
            validate_authority_matrix(data, self.registry)

    def test_saf_export_write_requires_distinct_authority_and_native_fence(
        self,
    ) -> None:
        base = {
            "host_authenticated": True,
            "scope": "user_consented",
            "operation": "create_document",
            "android_os_consent": True,
            "android_grant_evidence": "ANDROID_FRAMEWORK_CALLBACK",
            "independent_security_approved": True,
        }
        self.assertEqual(
            decide_request(self.matrix, "N11", base), "DENY_OPERATOR_APPROVAL"
        )
        base["operator_approval"] = True
        self.assertEqual(decide_request(self.matrix, "N11", base), "DENY_NATIVE_LEASE")
        base["native_lease"] = True
        self.assertEqual(
            decide_request(self.matrix, "N11", base), "PLAN_ONLY_NOT_LIVE_APPROVAL"
        )

    def test_explicit_app_launch_does_not_invent_android_os_permission_screen(
        self,
    ) -> None:
        request = {
            "host_authenticated": True,
            "scope": "approved_control",
            "android_os_consent": False,
            "operator_approval": True,
            "native_lease": True,
            "independent_security_approved": True,
            "target_is_owned_fixture": True,
        }
        self.assertEqual(
            decide_request(self.matrix, "N12", request), "PLAN_ONLY_NOT_LIVE_APPROVAL"
        )
        self.assertEqual(
            decide_request(self.matrix, "N12", {**request, "operator_approval": False}),
            "DENY_OPERATOR_APPROVAL",
        )


if __name__ == "__main__":
    unittest.main()

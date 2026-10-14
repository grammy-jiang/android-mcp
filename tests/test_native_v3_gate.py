"""Adversarial E00 product-evidence admission tests (offline, no devices)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.native_v3_gate import admit_emulator_case, audit_baseline

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = (
    ROOT
    / "docs/native-v3/Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json"
)
TRACE = (
    ROOT
    / "docs/native-v3/Android_Native_MCP_V3_Legacy_228_Traceability_Template_2026-10-14.csv"
)
PLAN = (
    ROOT / "docs/native-v3/Android_Native_MCP_E2E_Implementation_Plan_V3_2026-10-14.md"
)


class BaselineGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_inventory_has_20_192_228_70_and_none_counted_complete(self) -> None:
        result = audit_baseline(self.registry, TRACE, PLAN)
        self.assertEqual(result["capabilities"], 20)
        self.assertEqual(result["v3_cases"], 192)
        self.assertEqual(result["historical_cases"], 228)
        self.assertEqual(result["packages"], 70)
        self.assertEqual(result["emulator_features_done"], 0)

    def test_duplicate_case_cannot_be_hidden_behind_count(self) -> None:
        forged = copy.deepcopy(self.registry)
        forged["capability_families"][1]["tests"][0]["test_id"] = "V3-N01-01"
        with self.assertRaises(ValueError):
            audit_baseline(forged, TRACE, PLAN)

    def test_missing_one_historical_case_is_rejected(self) -> None:
        lines = TRACE.read_text(encoding="utf-8").splitlines()
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.csv"
            path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                audit_baseline(self.registry, path, PLAN)

    def test_synthetic_claim_never_admitted(self) -> None:
        forged = {
            "case_id": "V3-N01-01",
            "layer": "PASS_MOCK",
            "tool_call": {"name": "device_status"},
            "android_effect": {"status": "OK"},
            "os_oracle": {"observed": True},
            "api": 36,
        }
        self.assertFalse(admit_emulator_case(forged, trust_roots={}))

    def test_adb_side_effect_never_substitutes_for_native_api(self) -> None:
        forged = {
            "case_id": "V3-N09-01",
            "layer": "PASS_REAL_E2E",
            "executor": "adb shell input tap",
            "origin": "HOST_ADB",
            "api": 36,
            "os_oracle": {"observed": True},
        }
        self.assertFalse(admit_emulator_case(forged, trust_roots={}))

    def test_self_review_and_missing_trusted_oracle_never_admitted(self) -> None:
        forged = {
            "case_id": "V3-N01-01",
            "layer": "PASS_REAL_E2E",
            "executor": "NATIVE_APK",
            "origin": "ANDROID_FRAMEWORK",
            "api": 36,
            "git_sha": "a" * 40,
            "apk_sha256": "b" * 64,
            "fixture_sha256": "c" * 64,
            "os_oracle": {"observed": True, "signed_by": "same-process"},
            "self_review": "APPROVED",
        }
        self.assertFalse(admit_emulator_case(forged, trust_roots={}))

    def test_registry_cannot_credit_unsubstantiated_v3_pass(self) -> None:
        forged = copy.deepcopy(self.registry)
        forged["capability_families"][0]["tests"][0]["status"] = "PASS_REAL_E2E"
        with self.assertRaises(ValueError):
            audit_baseline(forged, TRACE, PLAN)


if __name__ == "__main__":
    unittest.main()

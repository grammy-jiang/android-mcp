"""Truthful, reproducible Native V3 GAP and work package inventory."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.native_v3_reconcile import reconcile

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
REG = (
    ROOT
    / "docs/native-v3/Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json"
)
PLAN = (
    ROOT / "docs/native-v3/Android_Native_MCP_E2E_Implementation_Plan_V3_2026-10-14.md"
)
LEDGER = ROOT / "docs/native-capability-ledger.v1.json"


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = json.loads(REG.read_text(encoding="utf-8"))
        self.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_all_20_incomplete_and_advertisement_from_actual_source(self) -> None:
        result = reconcile(self.reg, self.ledger, PLAN.read_text(), NATIVE.read_text())
        self.assertEqual(len(result["capabilities"]), 20)
        self.assertEqual(len(result["required_gaps"]), 20)
        self.assertEqual(
            {g["id"] for g in result["required_gaps"]},
            {f"GAP-N{x:02}-001" for x in range(1, 21)},
        )
        self.assertEqual(result["live_native_tool_names"], ["device_status"])
        self.assertEqual(result["production_features_done"], 0)
        self.assertEqual(result["verified_v3_cases"], 0)
        self.assertEqual(len(result["work_package_index"]), 70)
        self.assertIn("BLOCKED_EXTERNAL", result["capabilities"]["N19"]["release_gate"])
        self.assertIn(
            "UNSUPPORTED_BY_PLATFORM", result["capabilities"]["N20"]["release_gate"]
        )

    def test_fake_ledger_complete_cannot_upgrade(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        ledger["capabilities"][1]["status"] = "merged_verified"
        ledger["capabilities"][1]["feature_executable_in_production"] = True
        result = reconcile(self.reg, ledger, PLAN.read_text(), NATIVE.read_text())
        self.assertFalse(result["capabilities"]["N02"]["real_e2e_verified"])

    def test_missing_native_registry_does_not_infer_kotlin_class_tool(self) -> None:
        result = reconcile(self.reg, self.ledger, PLAN.read_text(), "")
        self.assertEqual(result["live_native_tool_names"], [])
        self.assertEqual(result["production_features_done"], 0)

    def test_plan_scope_cannot_be_silently_reduced(self) -> None:
        with self.assertRaises(ValueError):
            reconcile(
                self.reg, self.ledger, "no actual work packages", NATIVE.read_text()
            )


if __name__ == "__main__":
    unittest.main()

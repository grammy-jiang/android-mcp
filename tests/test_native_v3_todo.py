"""V3 checklist must list *all* work and never infer product completion."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.native_v3_todo import build_checklist, render_markdown

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs/native-v3/v3-execution-status.json"
PLAN = (
    ROOT / "docs/native-v3/Android_Native_MCP_E2E_Implementation_Plan_V3_2026-10-14.md"
)


class FullV3ChecklistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.status = json.loads(STATUS.read_text(encoding="utf-8"))
        self.config = {
            "E00.a": {
                "state": "PARTIAL",
                "note": "Original work registry and delivery summary not recovered",
            },
            "E00.b": {
                "state": "DONE_ENGINEERING",
                "note": "228 case source and actual unit XML traced",
                "evidence": [
                    "docs/native-v3/E00B-LEGACY-228-TRACEABILITY-EVIDENCE-20261014.md"
                ],
            },
            "E01.a": {
                "state": "DONE_ENGINEERING",
                "note": "4-API installed AndroidJUnitRunner",
                "evidence": ["docs/native-v3/E00-E01-EXECUTION-EVIDENCE-20261014.md"],
            },
            "E00.d": {
                "state": "IN_PROGRESS",
                "note": "Security/consent ownership audit in isolated worktree",
            },
        }

    def test_lists_every_package_and_open_gap_and_reports_product_incomplete(
        self,
    ) -> None:
        output = build_checklist(
            self.status, self.config, PLAN.read_text(encoding="utf-8"), ROOT
        )
        self.assertEqual(output["initial_work_packages"], 70)
        self.assertEqual(output["open_gaps"], 27)
        self.assertEqual(output["capabilities_done"], 0)
        self.assertEqual(len(output["tasks"]), 97)
        self.assertEqual(output["product_status"], "PRODUCT_INCOMPLETE")
        self.assertEqual(
            {x["id"] for x in output["tasks"] if x["kind"] == "package"},
            {x["id"] for x in self.status["work_package_index"]},
        )
        md = render_markdown(output)
        self.assertEqual(md.count("## E"), 16)
        self.assertIn("- [x] ~~E01.a", md)
        self.assertIn("- [ ] **E00.d", md)
        self.assertIn("GAP-N17-004", md)
        self.assertIn("PRODUCT_INCOMPLETE", md)

    def test_cannot_forge_done_without_a_versioned_evidence_file(self) -> None:
        data = copy.deepcopy(self.config)
        data["E02.d"] = {"state": "DONE_ENGINEERING", "note": "Just trust me"}
        with self.assertRaises(ValueError):
            build_checklist(self.status, data, PLAN.read_text(), ROOT)

    def test_cannot_hide_gaps_or_scope_by_relabeling_status(self) -> None:
        tampered = copy.deepcopy(self.status)
        tampered["required_gaps"] = tampered["required_gaps"][:-1]
        with self.assertRaises(ValueError):
            build_checklist(tampered, self.config, PLAN.read_text(), ROOT)

    def test_unknown_package_is_never_credited(self) -> None:
        overrides = copy.deepcopy(self.config)
        overrides["E16.a"] = {
            "state": "DONE_ENGINEERING",
            "note": "Not part of plan",
            "evidence": ["docs/native-v3/E00-E01-EXECUTION-EVIDENCE-20261014.md"],
        }
        with self.assertRaises(ValueError):
            build_checklist(self.status, overrides, PLAN.read_text(), ROOT)

    def test_product_status_cannot_be_downgraded_to_pass(self) -> None:
        bad = copy.deepcopy(self.status)
        bad["production_features_done"] = 20
        with self.assertRaises(ValueError):
            build_checklist(bad, self.config, PLAN.read_text(), ROOT)


if __name__ == "__main__":
    unittest.main()

"""GAP-N01-002: historical tests require real assertions, not names/comments."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from scripts.native_v3_legacy_assertion_audit import (
    AssertionAuditError,
    audit_kotlin_method,
    audit_python_method,
    build_assertion_audit,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[1]


class HistoricalAssertionAuditTests(unittest.TestCase):
    def test_every_case_has_source_pinned_executable_assertions_without_product_promotion(
        self,
    ) -> None:
        report = build_assertion_audit(ROOT)
        self.assertEqual(report["historical_cases"], 228)
        self.assertEqual(report["actual_test_methods"], 257)
        self.assertEqual(report["cases_with_assertions"], 228)
        self.assertEqual(report["methods_without_substantive_assertion"], 0)
        self.assertEqual(report["real_android_mcp_capabilities_proven"], 0)
        self.assertEqual(len(report["cases"]), 228)
        self.assertEqual(
            report["assertion_basis_by_method"],
            {
                "KOTLIN_JVM_ASSERTION": 216,
                "MOCKED_HARNESS_ASSERTION": 10,
                "PYTHON_UNIT_ASSERTION": 1,
                "SOURCE_STATIC_ASSERTION": 30,
            },
        )
        self.assertEqual(len({x["case_id"] for x in report["cases"]}), 228)
        self.assertTrue(
            all(
                row["requirement_semantic_review"] == "NOT_INDEPENDENTLY_REVIEWED"
                and row["product_e2e_status"] == "NOT_VERIFIED_REAL_ANDROID_E2E"
                for row in report["cases"]
            )
        )
        self.assertEqual(sum(len(x["methods"]) for x in report["cases"]), 257)
        validate_report(report, ROOT)

    def test_static_source_checks_never_promoted_to_runtime_android_evidence(
        self,
    ) -> None:
        report = build_assertion_audit(ROOT)
        source_only = next(x for x in report["cases"] if x["case_id"] == "T-N3A-03")
        self.assertTrue(
            any(
                method["basis"] == "SOURCE_STATIC_ASSERTION"
                for method in source_only["methods"]
            )
        )
        self.assertFalse(source_only["verified_android_effect"])
        jvm = next(x for x in report["cases"] if x["case_id"] == "T-N1A-01")
        self.assertEqual(jvm["methods"][0]["basis"], "KOTLIN_JVM_ASSERTION")
        self.assertFalse(jvm["verified_android_effect"])

    def test_python_function_must_contain_executed_relevant_assertion(self) -> None:
        good = "def test_T_N0A_01_real():\n    observed = 8\n    assert observed == 8\n"
        result = audit_python_method(good, "test_T_N0A_01_real")
        self.assertEqual(result["substantive_assertions"], 1)
        for bad in (
            "def test_T_N0A_01_real():\n    pass\n",
            'def test_T_N0A_01_real():\n    """assert 8 == 8"""\n',
            "def test_T_N0A_01_real():\n    # assert True\n    assert True\n",
            ("def test_T_N0A_01_real():\n    def nested():\n        assert observed\n"),
            (
                "def test_T_N0A_01_real():\n"
                "    import pytest\n    with pytest.raises(ValueError):\n        pass\n"
            ),
            (
                "def test_T_N0A_01_real():\n"
                "    import pytest\n    with pytest.raises(ValueError):\n"
                "        raise ValueError()\n"
            ),
        ):
            with self.subTest(bad=bad[:36]), self.assertRaises(AssertionAuditError):
                audit_python_method(bad, "test_T_N0A_01_real")

    def test_python_pytest_raises_requires_invoked_subject_not_comment(self) -> None:
        code = (
            "def test_T_N0A_01_raise():\n"
            "    import pytest\n"
            "    with pytest.raises(ValueError):\n"
            "        int('not-number')\n"
        )
        self.assertEqual(
            audit_python_method(code, "test_T_N0A_01_raise")["substantive_assertions"],
            1,
        )

    def test_kotlin_comments_strings_and_tautologies_cannot_fake_junit_assertion(
        self,
    ) -> None:
        valid = (
            "class RealTest {\n"
            "    @Test\n"
            "    fun tN1A01ShowsEffect() {\n"
            "        val result = 3\n"
            "        assertEquals(3, result)\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual(
            audit_kotlin_method(valid, "tN1A01ShowsEffect")["substantive_assertions"],
            1,
        )
        for misleading in (
            "    // assertEquals(1, 1)\n",
            '    val text = "assertFalse(false) { quote }"\n',
            "    /* assertTrue(1 == 1) */\n",
            "    assertTrue(true)\n",
        ):
            fake = valid.replace("        assertEquals(3, result)\n", misleading)
            with self.subTest(fake=misleading), self.assertRaises(AssertionAuditError):
                audit_kotlin_method(fake, "tN1A01ShowsEffect")

    def test_kotlin_nested_braces_do_not_truncate_assertions(self) -> None:
        code = (
            "class RealTest {\n"
            "    @Test fun tN1A01Nested() {\n"
            '        val example = "{ braces in a string }"\n'
            "        if (example.isNotEmpty()) {\n"
            "            assertFalse(example.isEmpty())\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual(
            audit_kotlin_method(code, "tN1A01Nested")["substantive_assertions"],
            1,
        )

    def test_local_native_quality_gate_verifies_checked_in_assertion_artifact(
        self,
    ) -> None:
        code = (ROOT / "scripts/check-native.sh").read_text(encoding="utf-8")
        self.assertIn(
            "-m scripts.native_v3_legacy_assertion_audit --repo . --verify", code
        )
        self.assertIn("test_native_v3_legacy_assertion_audit.py", code)

    def test_changed_source_line_digest_and_false_review_are_detected(self) -> None:
        result = build_assertion_audit(ROOT)
        tampered = copy.deepcopy(result)
        tampered["cases"][0]["methods"][0]["source_sha256"] = "0" * 64
        with self.assertRaises(AssertionAuditError):
            validate_report(tampered, ROOT)
        tampered = copy.deepcopy(result)
        tampered["cases"][0]["requirement_semantic_review"] = "FULLY_REVIEWED"
        with self.assertRaises(AssertionAuditError):
            validate_report(tampered, ROOT)
        tampered = copy.deepcopy(result)
        tampered["real_android_mcp_capabilities_proven"] = 20
        with self.assertRaises(AssertionAuditError):
            validate_report(tampered, ROOT)


if __name__ == "__main__":
    unittest.main()

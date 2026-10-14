"""E00.b exact executable historical 228-case attribution and adversarial regressions."""

from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from scripts.native_v3_legacy_attribution import build_attribution

ROOT = Path(__file__).resolve().parents[1]


class LegacyAttributionTests(unittest.TestCase):
    def test_all_228_have_exact_executable_test_selectors(self) -> None:
        result = build_attribution(ROOT)
        self.assertEqual(result["historical_specifications"], 228)
        self.assertEqual(result["unique_case_ids"], 228)
        self.assertEqual(result["case_id_with_executable_test"], 228)
        self.assertEqual(result["e2e_android_feature_verified"], 0)
        self.assertEqual(len(result["cases"]), 228)
        self.assertEqual(result["test_methods_discovered"], 257)
        methods = [
            method
            for record in result["cases"]
            for method in record["executable_test_identifiers"]
        ]
        self.assertEqual(len(methods), 257)
        self.assertEqual(len({m["source"] + ":" + m["function"] for m in methods}), 257)
        self.assertEqual(
            Counter(m["test_layer"] for m in methods),
            {"KOTLIN_JVM_JUNIT": 216, "PYTHON_UNIT_HARNESS": 41},
        )
        self.assertTrue(
            all(
                record["e2e_result"] == "NOT_VERIFIED_REAL_E2E"
                for record in result["cases"]
            )
        )
        self.assertTrue(
            all(record["case_id"].startswith("T-N") for record in result["cases"])
        )
        self.assertFalse(
            any(record["product_capability_done"] for record in result["cases"])
        )

    def test_explicit_test_names_not_comments_are_attributed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._minimal_fake_root(directory)
            fake = directory / "android/tests/test_injected.py"
            fake.write_text(
                '"""def test_T_N0A_01_fake(): pass"""\n'
                "# def test_T_N0A_01_sneaky(): pass\n"
                "def test_T_N0A_01_real():\n    assert True\n"
            )
            from scripts.native_v3_legacy_attribution import python_case_methods

            methods = python_case_methods(fake)
            self.assertEqual(set(methods), {"T-N0A-01"})
            self.assertEqual(len(methods["T-N0A-01"]), 1)
            self.assertEqual(methods["T-N0A-01"][0]["function"], "test_T_N0A_01_real")

    def test_missing_real_test_fails_closed(self) -> None:
        source = ROOT / "android/tests/test_native_status_golden.py"
        with tempfile.TemporaryDirectory() as temp:
            replacement = Path(temp) / "bad.py"
            replacement.write_text(
                source.read_text().replace(
                    "def test_T_N0A_01_catalog_has_no_hidden_resources(",
                    "def test_catalog_has_no_hidden_resources(",
                )
            )
            from scripts.native_v3_legacy_attribution import python_case_methods

            self.assertNotIn("T-N0A-01", python_case_methods(replacement))

    def test_kotlin_declaration_requires_junit_annotation(self) -> None:
        from scripts.native_v3_legacy_attribution import kotlin_case_methods

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "BadTest.kt"
            path.write_text(
                "class BadTest {\n"
                "    fun tN0A01FakeNoJUnit() {}\n"
                "    @Test\n"
                "    fun tN0A02RealJUnit() {}\n"
                "}\n"
            )
            result = kotlin_case_methods(path)
            self.assertNotIn("T-N0A-01", result)
            self.assertIn("T-N0A-02", result)

    def test_reference_mutation_rejects_missing_specification(self) -> None:
        import csv

        original = (
            ROOT
            / "docs/native-v3/Android_Native_MCP_V3_Legacy_228_Traceability_Template_2026-10-14.csv"
        )
        with original.open(newline="") as file:
            lines = list(csv.DictReader(file))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            with path.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(lines[0]))
                writer.writeheader()
                writer.writerows(lines[1:])
            from scripts.native_v3_legacy_attribution import validate_registry

            with self.assertRaises(ValueError):
                validate_registry(
                    path, ROOT / "docs/native-mcp-serial-test-cases-20261013.md"
                )

    def test_no_execution_credit_from_traced_method_count(self) -> None:
        result = build_attribution(ROOT)
        example = next(
            item for item in result["cases"] if item["case_id"] == "T-N7A-01"
        )
        self.assertTrue(example["executable_test_identifiers"])
        self.assertEqual(example["e2e_result"], "NOT_VERIFIED_REAL_E2E")
        self.assertEqual(
            example["per_android_api"],
            {
                "30": "NOT_VERIFIED_REAL_E2E",
                "33": "NOT_VERIFIED_REAL_E2E",
                "34": "NOT_VERIFIED_REAL_E2E",
                "36": "NOT_VERIFIED_REAL_E2E",
            },
        )
        self.assertIn("plan", example["requirement_description"].lower())

    @staticmethod
    def _minimal_fake_root(root: Path) -> None:
        (root / "android/tests").mkdir(parents=True)

    def test_runtime_junit_xml_join_attests_method_but_never_android_effect(
        self,
    ) -> None:
        import xml.etree.ElementTree as ET

        from scripts.native_v3_legacy_attribution import join_local_unit_results

        baseline = build_attribution(ROOT)
        sample = next(v for v in baseline["cases"] if v["case_id"] == "T-N1A-01")
        kotlin_method = sample["executable_test_identifiers"][0]
        self.assertEqual(kotlin_method["test_layer"], "KOTLIN_JVM_JUNIT")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kotlin_dir = root / "kotlin"
            kotlin_dir.mkdir()
            suite = ET.Element(
                "testsuite",
                name="org.androidmcp.protocol.NativeBuildSnapshotTest",
                tests="1",
                failures="0",
                errors="0",
            )
            ET.SubElement(
                suite,
                "testcase",
                classname="org.androidmcp.protocol.NativeBuildSnapshotTest",
                name=kotlin_method["function"] + "()",
            )
            ET.ElementTree(suite).write(kotlin_dir / "TEST-NativeBuildSnapshotTest.xml")
            result = join_local_unit_results(
                baseline,
                kotlin_dir,
                root / "does-not-exist.xml",
                root,
            )
            item = next(v for v in result["cases"] if v["case_id"] == "T-N1A-01")
            self.assertEqual(item["execution_record"], "PASS_REPORTED_KOTLIN_JVM")
            self.assertEqual(item["e2e_result"], "NOT_VERIFIED_REAL_E2E")
            self.assertEqual(result["e2e_android_feature_verified"], 0)
            suite[0].append(ET.Element("failure", message="failed"))
            ET.ElementTree(suite).write(kotlin_dir / "TEST-NativeBuildSnapshotTest.xml")
            failed = join_local_unit_results(
                baseline,
                kotlin_dir,
                root / "does-not-exist.xml",
                root,
            )
            item = next(v for v in failed["cases"] if v["case_id"] == "T-N1A-01")
            self.assertEqual(item["execution_record"], "FAIL_REPORTED_UNIT_TEST")

    def test_runtime_join_cannot_bypass_failure_with_second_xml(self) -> None:
        from scripts.native_v3_legacy_attribution import join_local_unit_results

        baseline = build_attribution(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for index in range(2):
                file = path / f"TEST-fake{index}.xml"
                file.write_text(
                    '<testsuite tests="1" failures="0" errors="0">'
                    '<testcase classname="org.androidmcp.protocol.NativeBuildSnapshotTest" '
                    'name="tN1A01RepresentativeBuildApiAbisNormalizeToVersionedSnapshot()" />'
                    "</testsuite>"
                )
            with self.assertRaises(ValueError):
                join_local_unit_results(baseline, path, path / "absent.xml", path)

    def test_python_parametrized_xml_name_maps_only_exact_function(self) -> None:
        from scripts.native_v3_legacy_attribution import join_local_unit_results

        baseline = build_attribution(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pytest.xml").write_text(
                '<testsuites><testsuite tests="1" failures="0" errors="0">'
                '<testcase classname="android.tests.test_native_status_golden" '
                'name="test_T_N0A_01_catalog_has_no_hidden_resources[variant]" />'
                "</testsuite></testsuites>"
            )
            result = join_local_unit_results(
                baseline,
                root / "no-kotlin",
                root / "pytest.xml",
                root,
            )
            item = next(v for v in result["cases"] if v["case_id"] == "T-N0A-01")
            self.assertEqual(item["execution_record"], "PASS_REPORTED_PYTHON_UNIT")
            wrong = next(v for v in result["cases"] if v["case_id"] == "T-N0A-02")
            self.assertEqual(wrong["execution_record"], "NOT_EXECUTED_IN_THIS_AUDIT")


if __name__ == "__main__":
    unittest.main()

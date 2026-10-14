"""E01.f test-first gate: no single-JVM/single-AVD false-green regression."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from scripts.native_v3_e2e_gate import GateError, evaluate_matrix

API_LEVELS = (30, 33, 34, 36)
GIT_SHA = "1" * 40
GIT_TREE = "2" * 40
APK = "3" * 64
TEST_APK = "4" * 64
FIXTURE_APK = "5" * 64
FIXTURE_TEST = "6" * 64
INSTALL_APK = "7" * 64
CERT = "8" * 64
DOC = "4ea8428c4dc75484e22c5832e3a564e1cc1c278cb4b1cb4fe87a3ac40d758fcf"
BOOTS = "-".join(["a" * 8, "a" * 4, "a" * 4, "a" * 4, "a" * 12])


def example(api: int) -> tuple[dict, dict]:
    name = f"android_mcp_native_v3_api{api}_20261014"
    serial = f"emulator-{ {30: 5564, 33: 5566, 34: 5568, 36: 5562}[api] }"
    owned = {
        "run_type": "V3_E01_BASELINE_NOT_PRODUCT_ACCEPTANCE",
        "api": api,
        "emulator": serial,
        "avd": name,
        "abi": "arm64-v8a",
        "boot_identity": BOOTS,
        "emulator_pid": api + 60000,
        "git_head": GIT_SHA,
        "git_tree": GIT_TREE,
        "apk_sha256": APK,
        "instrumentation_apk_sha256": TEST_APK,
        "instrumentation_tests": 3,
        "mcp_client": "FastMCP to installed Native Android APK",
        "independent_android_oracle": "PackageManager installed version/UID",
        "mcp_check": {
            "result": "pass",
            "registered_tools": 1,
            "physical_device_used": False,
            "environment": "verified_emulator_only",
            "transport": "adb_forward_to_local_mcp",
            "checks": ["install", "http_status", "home_stops", "resume_starts"],
        },
        "n01_emulator_function_done": False,
    }
    fixture = {
        "scope": "E01.b TEST_FIXTURE_ONLY_NOT_NATIVE_FEATURE",
        "status": "FIXTURE_READY",
        "api": api,
        "serial": serial,
        "avd": name,
        "emulator_pid": api + 60000,
        "boot_identity": BOOTS,
        "git_head": GIT_SHA,
        "git_tree": GIT_TREE,
        "signing": {
            "fixture_sha256": FIXTURE_APK,
            "install_target_sha256": INSTALL_APK,
            "fixture_certificate_sha256": CERT,
            "install_target_certificate_sha256": CERT,
        },
        "androidTest_sha256": FIXTURE_TEST,
        "document_bytes_sha256": DOC,
        "instrumentation": "12 real AndroidJUnitRunner tests",
        "external_counter_before": 7,
        "external_counter_after": 8,
        "counter_after_process_restart": 8,
        "os_direct_document_denied": True,
        "independent_screenshot_sha256": "9" * 64,
        "visual_colors": [[255, 64, 80], [21, 203, 131], [22, 137, 255]],
        "actual_native_mcp_tool_used": False,
        "product_case_passed": False,
        "installer_target": "signed APK validated, NOT installed by Native PackageInstaller",
    }
    return owned, fixture


def receipts() -> list[tuple[dict, dict]]:
    return [example(api) for api in API_LEVELS]


class E01MatrixGateTests(unittest.TestCase):
    def test_full_four_api_receipts_admitted_as_infrastructure_only(self) -> None:
        result = evaluate_matrix(receipts(), GIT_SHA, GIT_TREE)
        self.assertEqual(result["verified_api_levels"], [30, 33, 34, 36])
        self.assertEqual(result["android_junit_tests"], 60)
        self.assertEqual(result["native_mcp_client_calls_verified"], 4)
        self.assertEqual(result["native_product_features_done"], 0)
        self.assertEqual(result["product_status"], "PRODUCT_INCOMPLETE")
        self.assertEqual(result["status"], "PASS_E01_INFRASTRUCTURE_ONLY")

    def test_one_api_missing_fails_gate(self) -> None:
        with self.assertRaises(GateError):
            evaluate_matrix(receipts()[:3], GIT_SHA, GIT_TREE)

    def test_duplicate_api_cannot_cover_other_version(self) -> None:
        data = receipts()
        data[-1] = copy.deepcopy(data[0])
        with self.assertRaises(GateError):
            evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_tampered_expected_sha_or_tree_rejected(self) -> None:
        data = receipts()
        for attr in ("git_head", "git_tree"):
            forged = copy.deepcopy(data)
            forged[1][0][attr] = "f" * 40
            with self.subTest(attr=attr), self.assertRaises(GateError):
                evaluate_matrix(forged, GIT_SHA, GIT_TREE)

    def test_missing_actual_mcp_path_never_counts(self) -> None:
        for key, bad in (
            ("registered_tools", 0),
            ("result", "mock_pass"),
            ("transport", "standalone_kotlin_jvm"),
            ("checks", ["install", "http_status", "home_stops"]),
            ("physical_device_used", True),
        ):
            data = receipts()
            data[0][0]["mcp_check"][key] = bad
            with self.subTest(key=key), self.assertRaises(GateError):
                evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_fake_android_runner_result_fails(self) -> None:
        for key, bad in (
            ("instrumentation_tests", 0),
            ("independent_android_oracle", "ADB performed tool"),
            ("run_type", "PASS_REAL_E2E"),
            ("n01_emulator_function_done", True),
        ):
            data = receipts()
            data[1][0][key] = bad
            with self.subTest(key=key), self.assertRaises(GateError):
                evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_footprint_and_native_fixture_identity_must_match(self) -> None:
        for key, bad in (
            ("avd", "other"),
            ("boot_identity", "stale"),
            ("emulator_pid", -1),
            ("serial", "physical-device"),
            ("signing", {"fixture_sha256": "c" * 64}),
        ):
            data = receipts()
            data[2][1][key] = bad
            with self.subTest(key=key), self.assertRaises(GateError):
                evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_fixture_side_effect_refusal_and_restart_are_mandatory(self) -> None:
        for key, bad in (
            ("external_counter_after", 7),
            ("counter_after_process_restart", 3),
            ("os_direct_document_denied", False),
            ("independent_screenshot_sha256", "unknown"),
            ("instrumentation", "9 fake JVM tests"),
            ("actual_native_mcp_tool_used", True),
            ("product_case_passed", True),
        ):
            data = receipts()
            data[3][1][key] = bad
            with self.subTest(key=key), self.assertRaises(GateError):
                evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_broken_fixture_signature_or_bytes_blocks(self) -> None:
        for key, bad in (
            ("fixture_certificate_sha256", "f" * 64),
            ("install_target_sha256", "not a hash"),
        ):
            data = receipts()
            data[2][1]["signing"][key] = bad
            with self.subTest(key=key), self.assertRaises(GateError):
                evaluate_matrix(data, GIT_SHA, GIT_TREE)
        data = receipts()
        data[2][1]["document_bytes_sha256"] = "f" * 64
        with self.assertRaises(GateError):
            evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_wrong_api_serial_alias_and_weak_boot_id_denied(self) -> None:
        for which, key, bad in (
            (0, "emulator", "emulator-5554"),
            (1, "api", 34),
            (0, "boot_identity", "weak"),
            (0, "apk_sha256", "f" * 64),
            (1, "androidTest_sha256", "f" * 64),
        ):
            data = receipts()
            data[0][which][key] = bad
            with self.subTest(which=which, key=key), self.assertRaises(GateError):
                evaluate_matrix(data, GIT_SHA, GIT_TREE)

    def test_pr_local_ci_must_explicitly_run_real_android_suite(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        local = (repo / "scripts/check-native-local-ci.sh").read_text()
        script = repo / "scripts/check-native-v3-e2e.sh"
        self.assertIn("--v3-matrix", local)
        self.assertIn("bash scripts/check-native-v3-e2e.sh", local)
        self.assertTrue(script.is_file())
        content = script.read_text()
        self.assertIn(":app:assembleDebugAndroidTest", content)
        self.assertIn("scripts/native_v3_e2e_gate.py", content)
        self.assertIn("scripts/check-native-v3-fixtures.sh", content)

    def test_missing_executed_suite_cannot_be_replaced_by_one_jvm_result(self) -> None:
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from scripts.native_v3_e2e_gate import run_matrix

        with TemporaryDirectory() as location:
            root = Path(location)
            (root / "android").mkdir()
            (root / "android/gradlew").write_text("test")
            python = root / "python"
            python.write_text("test")
            python.chmod(0o700)
            # No real app or instrumentation APKs exist: fail before any mock
            # client could be wrongly credited as deployed Android effects.
            with (
                patch("scripts.native_v3_e2e_gate._run", return_value=""),
                self.assertRaises(GateError),
            ):
                run_matrix(root, python, root / "evidence")


if __name__ == "__main__":
    unittest.main()

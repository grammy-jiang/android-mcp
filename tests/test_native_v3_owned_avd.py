"""Offline negative-path tests for exclusive V3 emulator admission."""

from __future__ import annotations

import copy
import socket
import tempfile
import unittest
from pathlib import Path

from scripts.native_v3_owned_avd import (
    EXPECTED_NATIVE_ANDROID_TEST_NAMES,
    IdentityError,
    exclusive_avd_lock,
    validate_identity,
    verify_native_instrumentation_report,
)

BASE = {
    "avd": "android_mcp_native_v3_api36_20261014",
    "expected_serial": "emulator-5562",
    "expected_api": 36,
    "host": socket.gethostname(),
    "worktree": "android-mcp-native-v3-e00-e01-20261014",
    "pid": 61501,
    "disposable": True,
}
OBS = {
    "serial": "emulator-5562",
    "avd": BASE["avd"],
    "api": 36,
    "qemu": "1",
    "abi": "arm64-v8a",
    "boot_completed": "1",
    "boot_identity": "abcdef12-1234-1234-1234-123456789abc",
    "process": "/sdk/qemu-system-aarch64-headless -avd android_mcp_native_v3_api36_20261014 -port 5562",
}


class OwnedEmulatorTests(unittest.TestCase):
    def test_exact_identity_passes(self) -> None:
        validate_identity(BASE, OBS)

    def test_physical_target_rejected_even_with_matching_api(self) -> None:
        x = copy.deepcopy(OBS)
        x["qemu"] = "0"
        with self.assertRaises(IdentityError):
            validate_identity(BASE, x)

    def test_tampered_owner_and_api_rejected(self) -> None:
        for field, value in (
            ("disposable", False),
            ("avd", "other"),
            ("expected_api", 34),
            ("expected_serial", "device123"),
            ("host", "other-host"),
        ):
            owner = copy.deepcopy(BASE)
            owner[field] = value
            with self.subTest(field=field), self.assertRaises(IdentityError):
                validate_identity(owner, OBS)

    def test_boot_incomplete_and_wrong_abi_rejected(self) -> None:
        for field, value in (
            ("boot_identity", ""),
            ("boot_completed", ""),
            ("abi", "x86_64"),
            ("serial", "emulator-5554"),
            ("api", 34),
            ("avd", "another"),
            ("process", "/usr/bin/adb shell"),
            ("qemu", ""),
        ):
            observed = copy.deepcopy(OBS)
            observed[field] = value
            with self.subTest(field=field), self.assertRaises(IdentityError):
                validate_identity(BASE, observed)

    def test_instrumentation_verifies_exact_eight_real_android_methods(self) -> None:
        cases = sorted(EXPECTED_NATIVE_ANDROID_TEST_NAMES)
        source = "\n".join(
            "INSTRUMENTATION_STATUS: test=" + name for name in cases for _ in range(2)
        )
        good = source + "\nOK (8 tests)\nINSTRUMENTATION_CODE: -1\n"
        self.assertEqual(verify_native_instrumentation_report(good), cases)
        for bad in (
            good.replace(cases[0], "forged_method", 1),
            good.replace("OK (8 tests)", "OK (7 tests)"),
            good.replace("INSTRUMENTATION_CODE: -1", "INSTRUMENTATION_CODE: 0"),
        ):
            with self.assertRaises(RuntimeError):
                verify_native_instrumentation_report(bad)

    def test_reused_lease_cannot_run_parallel_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "exclusive.lock"
            with exclusive_avd_lock(path):  # noqa: SIM117 - intentional nested lease contention
                with self.assertRaises(BlockingIOError), exclusive_avd_lock(path):
                    pass
            with exclusive_avd_lock(path):
                pass


if __name__ == "__main__":
    unittest.main()

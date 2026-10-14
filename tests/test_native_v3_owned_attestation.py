"""E01.e test-first attested AVD identity, process epoch and renewal."""

from __future__ import annotations

import copy
import unittest

from scripts.native_v3_owned_avd import (
    IdentityError,
    create_owner_attestation,
    validate_test_run_nonce,
    verify_owner_attestation,
)

KEY = bytes.fromhex("a1" * 32)
KEY2 = bytes.fromhex("f5" * 32)
START = "Wed Oct 14 11:39:31 2026"
NOW = 1791949000
OWNER = {
    "avd": "android_mcp_native_v3_api36_20261014",
    "expected_serial": "emulator-5562",
    "expected_api": 36,
    "host": "Mac",
    "worktree": "android-mcp-native-v3-e00-e01-20261014",
    "pid": 61501,
    "disposable": True,
    "started_utc": 1791939000,
}
OBS = {
    "serial": "emulator-5562",
    "avd": OWNER["avd"],
    "api": 36,
    "qemu": "1",
    "abi": "arm64-v8a",
    "boot_completed": "1",
    "boot_identity": "abcdef12-1234-1234-1234-123456789abc",
    "process": "/sdk/qemu-system-aarch64-headless -avd android_mcp_native_v3_api36_20261014 -port 5562",
}
NONCE = "ab" * 16


def signed():
    return create_owner_attestation(OWNER, OBS, START, KEY, NONCE, NOW)


class OwnedAttestationTests(unittest.TestCase):
    def test_real_source_owner_process_and_boot_are_pinned(self):
        proof = signed()
        self.assertEqual(proof["schema"], "native-v3-avd-owner-attestation.v1")
        self.assertEqual(proof["nonce"], NONCE)
        self.assertEqual(proof["avd"], OWNER["avd"])
        self.assertEqual(proof["api"], 36)
        self.assertEqual(proof["serial"], "emulator-5562")
        self.assertTrue(
            verify_owner_attestation(proof, OWNER, OBS, START, KEY, NOW + 42)
        )

    def test_signed_owner_or_android_state_tampering_rejected(self):
        baseline = signed()
        for parent, field, value in (
            ("owner", "pid", 64555),
            ("owner", "host", "other-host"),
            ("owner", "started_utc", 1),
            ("observed", "boot_identity", "abcdef12-1234-1234-1234-aaaaaaaaaaaa"),
            ("observed", "abi", "x86_64"),
            ("observed", "qemu", "0"),
            ("observed", "avd", "android_mcp_native_api36"),
            ("observed", "serial", "physical-01"),
        ):
            owner = copy.deepcopy(OWNER)
            observed = copy.deepcopy(OBS)
            if parent == "owner":
                owner[field] = value
            else:
                observed[field] = value
            with self.subTest(field=field), self.assertRaises(IdentityError):
                verify_owner_attestation(baseline, owner, observed, START, KEY, NOW + 1)

    def test_wrong_key_nonce_signature_and_forged_issued_time_rejected(self):
        baseline = signed()
        with self.assertRaises(IdentityError):
            verify_owner_attestation(baseline, OWNER, OBS, START, KEY2, NOW + 1)
        for field, value in (
            ("nonce", "bc" * 16),
            ("signature", "0" * 64),
            ("issued_at_unix", NOW + 200),
            ("expiry_unix", NOW + 1000000),
            ("owner_sha256", "0" * 64),
            ("pid_start_sha256", "0" * 64),
            ("boot_id", "0" * 36),
            ("serial", "emulator-5554"),
        ):
            item = copy.deepcopy(baseline)
            item[field] = value
            with self.subTest(field=field), self.assertRaises(IdentityError):
                verify_owner_attestation(item, OWNER, OBS, START, KEY, NOW + 1)

    def test_pid_reuse_would_not_inherit_identity(self):
        with self.assertRaises(IdentityError):
            verify_owner_attestation(
                signed(), OWNER, OBS, "Thu Oct 15 12:00:00 2026", KEY, NOW + 4
            )

    def test_expired_and_future_attestation_rejected(self):
        proof = signed()
        with self.assertRaises(IdentityError):
            verify_owner_attestation(proof, OWNER, OBS, START, KEY, NOW + 86401)
        with self.assertRaises(IdentityError):
            verify_owner_attestation(proof, OWNER, OBS, START, KEY, NOW - 90)

    def test_legacy_unsigned_owner_is_not_attested(self):
        with self.assertRaises(IdentityError):
            verify_owner_attestation({}, OWNER, OBS, START, KEY, NOW)

    def test_malformed_nonce_not_allowed(self):
        for nonce in ("", "abc", "z" * 32, "0" * 128, "a" * 31, "a" * 32 + "\\n"):
            with self.subTest(nonce=nonce[:20]), self.assertRaises(IdentityError):
                validate_test_run_nonce(nonce)

    def test_random_per_run_nonce_format_and_never_fixed(self):
        import secrets

        one, two = secrets.token_hex(16), secrets.token_hex(16)
        self.assertNotEqual(one, two)
        self.assertEqual(validate_test_run_nonce(one), one)
        self.assertEqual(validate_test_run_nonce(two), two)


if __name__ == "__main__":
    unittest.main()

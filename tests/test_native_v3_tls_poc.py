"""E02.a offline adversarial tests for real AndroidKeyStore mutual TLS POC."""

from __future__ import annotations

import base64
import hashlib
import unittest

from scripts.native_v3_tls_poc import (
    POCError,
    assert_ciphertext,
    assert_expected_server_cert,
    parse_ready,
    validate_exclusive_tls_avd,
    verify_android_completion,
)

NONCE = "a" * 24
CERT = b"0123456789" * 30
CERT_B64 = base64.b64encode(CERT).decode()
LINE = f"10-14 14:00:00.000 123 I NativeV3TlsPoc: READY nonce={NONCE} port=44444 cert_base64={CERT_B64}"
OWNER = {
    "disposable": True,
    "avd": "android_mcp_native_v3_tls_api36_20261014",
    "serial": "emulator-5570",
    "api": 36,
    "abi": "arm64-v8a",
    "worktree": "android-mcp-native-v3-e02a-mtls-poc-20261014",
    "pid": 7780,
    "host": "Mac",
}
OBS = {
    "serial": "emulator-5570",
    "avd": OWNER["avd"],
    "api": 36,
    "abi": "arm64-v8a",
    "qemu": "1",
    "boot_completed": "1",
    "process": f"qemu-system-aarch64-headless -avd {OWNER['avd']} -port 5570",
    "boot_identity": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
}
COMPLETION = (
    f"10-14 14:01:00 I NativeV3TlsPoc: COMPLETE nonce={NONCE} allowed=1 denied=2\n"
)


class MutualTlsPocGateTests(unittest.TestCase):
    def test_pinned_public_readiness_only_exact_nonce(self) -> None:
        port, certificate = parse_ready(LINE, NONCE)
        self.assertEqual(port, 44444)
        self.assertEqual(certificate, CERT)

    def test_missing_duplicate_or_wrong_run_cert_refused(self) -> None:
        for bad in (
            "",
            LINE + "\n" + LINE,
            LINE.replace(NONCE, "b" * 24),
            LINE.replace("44444", "0"),
            LINE.replace(CERT_B64, "%%%"),
        ):
            with self.subTest(bad=bad[:50]), self.assertRaises(POCError):
                parse_ready(bad, NONCE)

    def test_android_runner_requires_three_mutual_auth_callbacks(self) -> None:
        result = "OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
        verify_android_completion(COMPLETION, result, NONCE)

    def test_no_cert_only_or_success_without_denial_fails(self) -> None:
        result = "OK (1 test)\nINSTRUMENTATION_CODE: -1"
        for logs, instrumentation in (
            (COMPLETION.replace("allowed=1", "allowed=3"), result),
            (COMPLETION.replace("denied=2", "denied=0"), result),
            (COMPLETION, result.replace("OK (1 test)", "OK (0 tests)")),
            (COMPLETION, "FAILURES!!!\nINSTRUMENTATION_CODE: -1"),
            (COMPLETION.replace(NONCE, "f" * 24), result),
        ):
            with self.subTest(logs=logs[:65]), self.assertRaises(POCError):
                verify_android_completion(logs, instrumentation, NONCE)

    def test_wire_capture_proves_no_plaintext_marker(self) -> None:
        sample = (
            b"\x16\x03\x03\x00\x05"
            + b"\x04\x05\x06\x07\x08"
            + b"\x17\x03\x03\x00\x02\xaa\xbb"
        )
        assert_ciphertext(sample, NONCE)

    def test_raw_plaintext_or_empty_capture_cannot_pass(self) -> None:
        for value in (
            b"",
            b"POC=" + NONCE.encode(),
            b"\x16\x03\x03\x00\x02POC=" + NONCE.encode(),
            b"GET /mcp HTTP/1.1",
        ):
            with self.subTest(value=value[:18]), self.assertRaises(POCError):
                assert_ciphertext(value, NONCE)

    def test_server_cert_pinned_by_sha256(self) -> None:
        sha = hashlib.sha256(CERT).hexdigest()
        assert_expected_server_cert(CERT, sha)
        with self.assertRaises(POCError):
            assert_expected_server_cert(CERT, hashlib.sha256(b"attacker").hexdigest())

    def test_only_exclusively_owned_qemu_is_admissible(self) -> None:
        validate_exclusive_tls_avd(OWNER, OBS)
        for key, value in (
            ("serial", "physical-android"),
            ("avd", "another-avd"),
            ("api", 34),
            ("qemu", "0"),
            ("boot_identity", ""),
            ("process", "adb emulator-5570"),
            ("boot_completed", ""),
        ):
            observed = {**OBS, key: value}
            with self.subTest(key=key), self.assertRaises(POCError):
                validate_exclusive_tls_avd(OWNER, observed)


if __name__ == "__main__":
    unittest.main()

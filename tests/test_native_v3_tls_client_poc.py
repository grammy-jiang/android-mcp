"""E02.a adversarial TLS client POC certificate and completion tests."""

from __future__ import annotations

import base64
import ssl
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from scripts.native_v3_tls_poc import POCError
from scripts.run_native_v3_tls_client_poc import (
    create_host_certificate,
    parse_android_complete,
    parse_android_ready,
    trusted_host_server,
)

NONCE = "a" * 24
TAG = "NativeV3TlsClient"
P = 39145


def sample_ready(der: bytes) -> str:
    return (
        f"10-14 14:00:00 I {TAG}: READY nonce={NONCE} port={P} "
        f"cert_base64={base64.b64encode(der).decode()}\n"
    )


class MutualTlsClientPocTests(unittest.TestCase):
    def test_ephemeral_host_identity_is_server_auth_only_local_san(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            der, pem, key = create_host_certificate(Path(temp))
            parsed = x509.load_der_x509_certificate(der)
            self.assertEqual(
                parsed.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value[
                    0
                ],
                ExtendedKeyUsageOID.SERVER_AUTH,
            )
            san = parsed.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            self.assertEqual(
                [str(x) for x in san.get_values_for_type(x509.IPAddress)], ["127.0.0.1"]
            )
            self.assertFalse(
                parsed.extensions.get_extension_for_class(
                    x509.BasicConstraints
                ).value.ca
            )
            self.assertTrue(pem.is_file())
            self.assertTrue(key.is_file())
            self.assertNotIn(b"PRIVATE KEY", pem.read_bytes())
            self.assertIn(b"PRIVATE KEY", key.read_bytes())
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_current_epoch_android_public_cert_parsed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cert, _, _ = create_host_certificate(Path(temp))
            self.assertEqual(parse_android_ready(sample_ready(cert), NONCE), cert)
            for data in (
                "",
                sample_ready(cert) * 2,
                sample_ready(cert).replace(NONCE, "b" * 24),
                sample_ready(cert).replace("39145", "0"),
                sample_ready(cert).replace(base64.b64encode(cert).decode(), "%%%"),
                sample_ready(cert).replace(
                    base64.b64encode(cert).decode(),
                    base64.b64encode(b"fake-asn1").decode(),
                ),
            ):
                with self.subTest(data=data[:85]), self.assertRaises(POCError):
                    parse_android_ready(data, NONCE)

    def test_server_tls_context_requires_trusted_android_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public, cert, key = create_host_certificate(root)
            context = trusted_host_server(cert, key, public)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
            self.assertEqual(context.maximum_version, ssl.TLSVersion.TLSv1_2)
            self.assertTrue(context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN)

    def test_android_completion_cannot_hide_missing_denial_or_failing_runner(
        self,
    ) -> None:
        complete = (
            f"10-14 14:01:00 I {TAG}: COMPLETE nonce={NONCE} allowed=1 denied=2\n"
        )
        passing = "Time 1.08\nOK (1 test)\nINSTRUMENTATION_CODE: -1"
        parse_android_complete(complete, passing, NONCE)
        for text, result in (
            ("", passing),
            (complete.replace("allowed=1", "allowed=3"), passing),
            (complete.replace("denied=2", "denied=0"), passing),
            (complete, "OK (1 test)\nFAILURES!!!\nINSTRUMENTATION_CODE: -1"),
            (complete, "OK (0 tests)\nINSTRUMENTATION_CODE: -1"),
            (complete.replace(NONCE, "f" * 24), passing),
        ):
            with self.subTest(text=text[:30]), self.assertRaises(POCError):
                parse_android_complete(text, result, NONCE)


if __name__ == "__main__":
    unittest.main()

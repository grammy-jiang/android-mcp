"""E02.b preview v2 security wire: adversarial Python Host reference validation.

Only proves protocol parsing and negative bounds, not Native/Host pairing or
Android consent. Release/feature state always PRODUCT_INCOMPLETE.
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.native_v3_contract_v2 import ContractError, encode_frame, validate_frame

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts/v2/native-security-envelope.v2.schema.json"
FIXTURES = ROOT / "contracts/v2/fixtures"
KINDS = (
    "pair_challenge",
    "pair_proof",
    "session_authorization",
    "operation_grant",
    "lease_acquire",
    "lease_receipt",
)
ISSUED = 1791940000000


def wire(kind: str) -> dict:
    return json.loads((FIXTURES / f"{kind}.v2.json").read_text())


class SharedV2ContractTests(unittest.TestCase):
    def test_signed_protocol_is_not_frozen_or_granted_by_schema(self) -> None:
        import hashlib

        manifest = json.loads(
            (ROOT / "contracts/v2/contract-manifest.json").read_text()
        )
        self.assertEqual(manifest["spec_status"], "C0_CANDIDATE_NOT_FROZEN")
        self.assertEqual(
            manifest["schema_sha256"], hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
        )
        self.assertEqual(manifest["host_live_runtime_consumer"], "NOT_CONNECTED")
        self.assertEqual(manifest["native_live_mcp_runtime_consumer"], "NOT_CONNECTED")
        self.assertEqual(
            manifest["cross_runtime_signature_canonicalization"], "BLOCKED_REVIEW"
        )
        self.assertFalse(manifest["production_pairing_enabled"])
        self.assertFalse(manifest["grants_authority"])
        self.assertEqual(manifest["real_android_e2e_features_done"], 0)

    def test_contract_self_validates_using_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(json.loads(SCHEMA.read_text()))

    def test_all_six_genuine_versioned_examples_valid(self) -> None:
        schema = json.loads(SCHEMA.read_text())
        validator = Draft202012Validator(schema)
        self.assertEqual(len(KINDS), 6)
        for kind in KINDS:
            obj = wire(kind)
            with self.subTest(kind=kind):
                self.assertEqual(list(validator.iter_errors(obj)), [])
                validated = validate_frame(
                    obj,
                    now_ms=ISSUED + 500,
                    expected_host_sha="2" * 64,
                    expected_native_sha="3" * 64,
                    expected_boot=obj["native_boot_epoch"],
                )
                self.assertEqual(validated.kind, kind)
                self.assertEqual(validated.session_id, obj["session_id"])
                self.assertEqual(
                    json.loads(encode_frame(validated)),
                    obj,
                    "Host adapter must round-trip exact meaning",
                )

    def test_any_model_approved_field_or_unknown_sensitive_key_rejected(self) -> None:
        schema = Draft202012Validator(json.loads(SCHEMA.read_text()))
        for kind in KINDS:
            for change in (
                {"approved": True},
                {"private_key": "demo"},
                {"bearer_token": "fake"},
                {"scope": "root"},
            ):
                data = wire(kind)
                data.update(change)
                with self.subTest(kind=kind, change=change):
                    self.assertFalse(schema.is_valid(data))

    def test_version_downgrade_and_invalid_payload_rejected(self) -> None:
        validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
        for kind in KINDS:
            for key, bad in (
                ("schema_version", 1),
                ("kind", "root_shell"),
                ("native_boot_epoch", "emulator-5554"),
                ("host_spki_sha256", "invalid"),
                ("issued_at_unix_ms", -1),
                ("expires_at_unix_ms", "tomorrow"),
            ):
                data = wire(kind)
                data[key] = bad
                with self.subTest(kind=kind, key=key):
                    self.assertFalse(validator.is_valid(data))

    def test_payload_variants_exact_shape_and_sensitive_boundaries(self) -> None:
        validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
        for kind in KINDS:
            for field, bad in (
                ("unknown_payload", 1),
                ("approved", True),
                ("command", "rm -rf /"),
            ):
                data = wire(kind)
                data["payload"][field] = bad
                with self.subTest(kind=kind, field=field):
                    self.assertFalse(validator.is_valid(data))
        challenge = wire("pair_challenge")
        challenge["payload"]["nonce_b64u"] = "too-short"
        self.assertFalse(validator.is_valid(challenge))
        lease = wire("lease_acquire")
        lease["payload"]["ttl_ms"] = 100000000
        self.assertFalse(validator.is_valid(lease))
        grant = wire("operation_grant")
        grant["payload"]["target_package"] = "/sdcard/secret"
        self.assertFalse(validator.is_valid(grant))

    def test_expiry_replay_and_wrong_fingerprint_fail_semantic_check(self) -> None:
        for kind in KINDS:
            good = wire(kind)
            for attribute, value in (
                ("issued_at_unix_ms", ISSUED + 2000),
                ("expires_at_unix_ms", ISSUED - 1),
                ("host_spki_sha256", "e" * 64),
                ("native_spki_sha256", "f" * 64),
                ("native_boot_epoch", "00000000-0000-4000-8000-000000000000"),
            ):
                altered = copy.deepcopy(good)
                altered[attribute] = value
                with (
                    self.subTest(kind=kind, attribute=attribute),
                    self.assertRaises(ContractError),
                ):
                    validate_frame(
                        altered,
                        now_ms=ISSUED + 500,
                        expected_host_sha="2" * 64,
                        expected_native_sha="3" * 64,
                        expected_boot=good["native_boot_epoch"],
                    )

    def test_unknown_payload_binding_and_grant_not_authority(self) -> None:
        grant = wire("operation_grant")
        accepted = validate_frame(
            grant,
            now_ms=ISSUED + 500,
            expected_host_sha="2" * 64,
            expected_native_sha="3" * 64,
            expected_boot=grant["native_boot_epoch"],
        )
        self.assertFalse(accepted.authorized)
        self.assertFalse(accepted.consent_verified)
        self.assertFalse(accepted.lease_held)
        self.assertFalse(accepted.product_complete)

    def test_malformed_wire_and_unbounded_frames_fail(self) -> None:
        from scripts.native_v3_contract_v2 import parse_frame

        for payload in (
            b"",
            b"{}",
            b"[]",
            b'{"schema_version":2}',
            b'{"schema_version":2,"schema_version":2}',
            b'{"root_shell":true}',
            b"x" * 9000,
            b"\xff" * 20,
        ):
            with self.subTest(payload=payload[:35]), self.assertRaises(ContractError):
                parse_frame(
                    payload,
                    now_ms=ISSUED + 500,
                    expected_host_sha="2" * 64,
                    expected_native_sha="3" * 64,
                    expected_boot=wire("pair_challenge")["native_boot_epoch"],
                )


if __name__ == "__main__":
    unittest.main()

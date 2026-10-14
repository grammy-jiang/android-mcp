"""E00.c real-path signed case/admission gates, no product self-certification."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.native_v3_case_admission import (
    AdmissionError,
    assess_case,
    assess_case_matrix,
    canonical_payload,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads(
    (
        ROOT
        / "docs/native-v3/Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json"
    ).read_text(encoding="utf-8")
)
NOW = 1791950000
SHA = "a" * 40
TREE = "b" * 40
APP_SHA = "c" * 64
FIXTURE_SHA = "d" * 64


def proof(api: int = 36, mutate=None) -> tuple[dict, dict, dict]:
    oracle_private = Ed25519PrivateKey.generate()
    reviewer_private = Ed25519PrivateKey.generate()
    oracle_key = oracle_private.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    review_key = reviewer_private.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    record = {
        "schema": "native-v3-real-e2e-evidence.v1",
        "case_id": "V3-N03-01",
        "api": api,
        "receipt_id": "r" + str(api) + "x" * 20,
        "source_git_sha": SHA,
        "source_git_tree": TREE,
        "installed_apk_sha256": APP_SHA,
        "independent_fixture_sha256": FIXTURE_SHA,
        "emulator": {
            "owner_worktree": "native-v3-dedicated-disposable",
            "serial": f"emulator-{ {30: 5564, 33: 5566, 34: 5568, 36: 5562}[api] }",
            "qemu": True,
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "os_api": api,
            "api_verified_by": "ANDROID_FRAMEWORK",
        },
        "session": {
            "paired_host_fingerprint": "e" * 64,
            "principal_id": "host:independent-A",
            "scope": "read",
            "auth_result": "MUTUAL_TLS_PAIRED",
            "consent": "NOT_REQUIRED_OS_READ",
            "boot_id": "12345678-1234-1234-1234-123456789abc",
        },
        "mcp_request": {
            "protocol": "mcp_streamable_http",
            "method": "tools/call",
            "tool": "native_system_snapshot",
            "message_id": "req123",
            "args_sha256": "f" * 64,
            "executor": "NATIVE_APK",
        },
        "mcp_response": {
            "message_id": "req123",
            "is_error": False,
            "result_kind": "ANDROID_FRAMEWORK_READ",
            "result_sha256": "0" * 64,
        },
        "android_callback": {
            "invocation_id": "req123",
            "package": "org.androidmcp.nativeapp",
            "api_name": "android.os.BatteryManager",
            "android_pid": 10240,
            "caller_pid": 10240,
            "time_ms": NOW * 1000 + 500,
            "result_sha256": "0" * 64,
        },
        "oracle": {
            "observer_app": "org.androidmcp.v3fixture",
            "observer_pid": 10300,
            "observer_role": "INDEPENDENT_ANDROID_OS_FIXTURE",
            "independent_observer_boot_id": "12345678-1234-1234-1234-123456789abc",
            "measurement_before_sha256": "1" * 64,
            "measurement_after_sha256": "2" * 64,
            "observed_result_sha256": "0" * 64,
            "observed_android_api": api,
            "linked_invocation_id": "req123",
            "time_ms": NOW * 1000 + 550,
            "causality": "NATIVE_FRAMEWORK_CALLBACK",
            "observed": True,
            "key_id": "independent-oracle-001",
        },
        "negative_recovery": {
            kind: {
                "status": "PASS_REAL_ANDROID_NEGATIVE",
                "observer_role": "INDEPENDENT_ANDROID_OS_FIXTURE",
                "android_api": api,
                "evidence_sha256": "3" * 64,
            }
            for kind in (
                "unauthenticated",
                "permission_refusal",
                "cancel",
                "user_stop",
                "timeout",
                "process_death",
                "retry",
                "concurrent",
                "cleanup",
            )
        },
        "artifact": {
            "executor": "NATIVE_APK",
            "production_sensitive_data": False,
            "bounded": True,
            "cleanup_released": True,
        },
        "collected_by": "dev:developer-not-oracle",
        "executed_at_ms": NOW * 1000,
        "oracle_signature": None,
        "review": {
            "schema": "native-v3-evidence-review.v1",
            "reviewer_id": "external-independent-reviewer",
            "key_id": "independent-reviewer-001",
            "role": "INDEPENDENT_EVIDENCE_REVIEW",
            "decision": "ACCEPT_CASE_EVIDENCE_NOT_FEATURE_RELEASE",
            "review_time_ms": NOW * 1000 + 800,
            "receipt_digest": None,
            "signature": None,
        },
    }
    if mutate is not None:
        mutate(record)
    payload = canonical_payload(record)
    record["oracle_signature"] = oracle_private.sign(payload).hex()
    digest = hashlib.sha256(payload).hexdigest()
    record["review"]["receipt_digest"] = digest
    review_payload = json.dumps(
        {
            "schema": "native-v3-evidence-review.v1",
            "reviewer_id": record["review"]["reviewer_id"],
            "key_id": record["review"]["key_id"],
            "role": record["review"]["role"],
            "decision": record["review"]["decision"],
            "review_time_ms": record["review"]["review_time_ms"],
            "receipt_digest": digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    record["review"]["signature"] = reviewer_private.sign(review_payload).hex()
    return (
        record,
        {"independent-oracle-001": oracle_key},
        {"independent-reviewer-001": review_key},
    )


class EvidenceAdmissionTests(unittest.TestCase):
    def valid(self):
        case, oracle, reviewer = proof()
        return assess_case(case, REGISTRY, oracle, reviewer, NOW, SHA, TREE)

    def test_policy_trusted_two_keys_marks_one_case_not_a_product(self) -> None:
        result = self.valid()
        self.assertEqual(result["case_id"], "V3-N03-01")
        self.assertEqual(
            result["evidence"], "CONDITIONAL_ATTESTED_CASE_NOT_PRODUCT_RELEASE"
        )
        self.assertFalse(result["feature_done"])
        self.assertFalse(result["production_security_released"])

    def test_model_self_review_never_accepted(self) -> None:
        record, trusted_oracle, trusted_reviewer = proof(
            mutate=lambda row: row["review"].update(reviewer_id=row["collected_by"])
        )
        with self.assertRaises(AdmissionError):
            assess_case(
                record, REGISTRY, trusted_oracle, trusted_reviewer, NOW, SHA, TREE
            )

    def test_missing_any_trust_root_or_wrong_signature_denied(self) -> None:
        record, oracle, reviewer = proof()
        for o, r in (({}, reviewer), (oracle, {}), ({"bad": b"1" * 32}, reviewer)):
            with self.assertRaises(AdmissionError):
                assess_case(record, REGISTRY, o, r, NOW, SHA, TREE)
        broken = copy.deepcopy(record)
        broken["oracle_signature"] = "f" * 128
        with self.assertRaises(AdmissionError):
            assess_case(broken, REGISTRY, oracle, reviewer, NOW, SHA, TREE)

    def test_signed_binding_fails_if_any_real_path_part_tampered(self) -> None:
        cases = [
            (("mcp_request", "executor"), "HOST_ADB"),
            (("mcp_request", "method"), "mock/plan"),
            (("mcp_response", "result_kind"), "FIXED_DENIED"),
            (("mcp_response", "message_id"), "different"),
            (("session", "auth_result"), "LOOPBACK_ONLY"),
            (("session", "scope"), "no_scope"),
            (("android_callback", "package"), "com.other"),
            (("android_callback", "result_sha256"), "c" * 64),
            (("oracle", "causality"), "ADB_MUTATED_STATE"),
            (("oracle", "observer_app"), "org.androidmcp.nativeapp"),
            (("oracle", "observed_result_sha256"), "1" * 64),
            (("negative_recovery", "user_stop"), "MOCK_PASS"),
            (("artifact", "bounded"), False),
            (("artifact", "cleanup_released"), False),
        ]
        for path, value in cases:
            forged, oracle, reviewer = proof(
                mutate=lambda row, path=path, value=value: row[path[0]].update(
                    {path[1]: value}
                )
            )
            with self.subTest(path=path), self.assertRaises(AdmissionError):
                assess_case(forged, REGISTRY, oracle, reviewer, NOW, SHA, TREE)

    def test_no_stale_boot_or_api_version_confusion(self) -> None:
        record, oracle, reviewer = proof(
            mutate=lambda row: row["emulator"].update(os_api=30)
        )
        with self.assertRaises(AdmissionError):
            assess_case(record, REGISTRY, oracle, reviewer, NOW, SHA, TREE)
        record, oracle, reviewer = proof(
            mutate=lambda row: row["session"].update(boot_id="f" * 36)
        )
        with self.assertRaises(AdmissionError):
            assess_case(record, REGISTRY, oracle, reviewer, NOW, SHA, TREE)

    def test_weak_or_mismatched_time_and_provenance_fails(self) -> None:
        record, oracle, reviewer = proof()
        for clock, head, tree in (
            (NOW - 900, SHA, TREE),
            (NOW, "z" * 40, TREE),
            (NOW, SHA, "f" * 40),
        ):
            with (
                self.subTest(clock=clock, head=head[:4]),
                self.assertRaises(AdmissionError),
            ):
                assess_case(record, REGISTRY, oracle, reviewer, clock, head, tree)

    def test_duplicate_stale_or_missing_android_api_blocks_matrix(self) -> None:
        receipts = [proof(api) for api in (30, 33, 34, 36)]
        passed = assess_case_matrix(receipts, REGISTRY, NOW, SHA, TREE)
        self.assertEqual(passed["apis"], [30, 33, 34, 36])
        self.assertEqual(passed["passed_cases"], 1)
        self.assertEqual(passed["features_done"], 0)
        with self.assertRaises(AdmissionError):
            assess_case_matrix(receipts[:3], REGISTRY, NOW, SHA, TREE)
        with self.assertRaises(AdmissionError):
            assess_case_matrix(
                receipts[:3] + [copy.deepcopy(receipts[0])], REGISTRY, NOW, SHA, TREE
            )

    def test_witness_key_and_reviewer_key_cannot_be_same(self) -> None:
        record, oracle, reviewer = proof()
        same = {key: next(iter(oracle.values())) for key in reviewer}
        with self.assertRaises(AdmissionError):
            assess_case(record, REGISTRY, oracle, same, NOW, SHA, TREE)

    def test_unregistered_or_denial_only_not_real_capability(self) -> None:
        record, oracle, reviewer = proof(
            mutate=lambda row: row.update(case_id="V3-N21-01")
        )
        with self.assertRaises(AdmissionError):
            assess_case(record, REGISTRY, oracle, reviewer, NOW, SHA, TREE)
        record, oracle, reviewer = proof(
            mutate=lambda row: row["mcp_response"].update(is_error=True)
        )
        with self.assertRaises(AdmissionError):
            assess_case(record, REGISTRY, oracle, reviewer, NOW, SHA, TREE)


if __name__ == "__main__":
    unittest.main()

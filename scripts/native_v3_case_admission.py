#!/usr/bin/env python3
"""E00.c strict real-Android case receipt admission and separate release gating.

A signed source-defined case record has integrity ONLY relative to trusted
independently provisioned public roots. A test can generate private keys and
prove crypto policy mechanics, but that is NOT independent acceptance proof.
This tool never creates/signs a receipt or provides production trust roots.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APIS = (30, 33, 34, 36)
SERIALS = {
    30: "emulator-5564",
    33: "emulator-5566",
    34: "emulator-5568",
    36: "emulator-5562",
}
NEGATIVE_KEYS = frozenset(
    (
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
)
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
HEX_GIT = re.compile(r"[0-9a-f]{40}\Z")
BOOT_ID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
CASE_ID = re.compile(
    r"V3-(?:N(?:0[1-9]|1[0-9]|20)-0[1-8]|XR-(?:0[1-9]|[12][0-9]|3[012]))\Z"
)
ALLOWED_SOURCE_METHODS = frozenset(("tools/call",))


class AdmissionError(ValueError):
    """Evidence was missing, untrusted, stale, unscoped or synthetic."""


def _require(predicate: bool, why: str) -> None:
    if not predicate:
        raise AdmissionError(why)


def _sha(text: Any) -> bool:
    return isinstance(text, str) and HEX_SHA256.fullmatch(text) is not None


def _git(text: Any) -> bool:
    return isinstance(text, str) and HEX_GIT.fullmatch(text) is not None


def _bounded_object(record: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise AdmissionError(
            "Malformed receipt contains non-JSON or NaN values"
        ) from error
    _require(len(encoded.encode("utf-8")) <= 65536, "Unbounded evidence response")
    _require(
        all(
            k in record
            for k in (
                "schema",
                "case_id",
                "api",
                "receipt_id",
                "source_git_sha",
                "source_git_tree",
                "installed_apk_sha256",
                "independent_fixture_sha256",
                "emulator",
                "session",
                "mcp_request",
                "mcp_response",
                "android_callback",
                "oracle",
                "negative_recovery",
                "artifact",
                "collected_by",
                "executed_at_ms",
                "oracle_signature",
                "review",
            )
        ),
        "Missing mandatory binding in signed receipt",
    )


def canonical_payload(receipt: dict[str, Any]) -> bytes:
    """Canonical E00.c oracle signature covers all evidence fields and context.

    Reviewer has a *separate* detached signature over exact oracle payload
    digest; excluding entire 'review' prevents cross-signature recursion.
    """
    if not isinstance(receipt, dict):
        raise AdmissionError("Receipt is not an object")
    _bounded_object(receipt)
    payload = {
        key: value
        for key, value in receipt.items()
        if key not in ("review", "oracle_signature")
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _verify_signature(
    public_key: Any, signature: Any, payload: bytes, why: str
) -> None:
    _require(
        isinstance(public_key, bytes) and len(public_key) == 32,
        f"{why}: independently pinned Ed25519 public key missing",
    )
    _require(
        isinstance(signature, str)
        and re.fullmatch(r"[0-9a-f]{128}", signature) is not None,
        f"{why}: signature malformed",
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(signature), payload
        )
    except (ValueError, TypeError, InvalidSignature) as error:
        raise AdmissionError(f"{why}: detached signature did not verify") from error


def _registered_id(registry: dict[str, Any], case_id: Any) -> bool:
    if not isinstance(case_id, str) or CASE_ID.fullmatch(case_id) is None:
        return False
    family_ids = {
        t.get("test_id")
        for f in registry.get("capability_families", [])
        for t in f.get("tests", [])
    }
    cross_ids = {c.get("test_id") for c in registry.get("crosscut_cases", [])}
    if len(family_ids) != 160 or len(cross_ids) != 32:
        return False
    return case_id in family_ids | cross_ids


def assess_case(
    record: dict[str, Any],
    registry: dict[str, Any],
    oracle_roots: dict[str, bytes],
    reviewer_roots: dict[str, bytes],
    now_seconds: int,
    expected_source_sha: str,
    expected_git_tree: str,
) -> dict[str, Any]:
    """Verify integrity, exact Android executor and independent review role.

    In a local test, a caller can supply test private/public keys; as such
    the result is deliberately *conditional policy evidence*, NEVER product
    PASS_REAL_E2E or an independent human security review.
    """
    _require(isinstance(record, dict), "No case receipt")
    _bounded_object(record)
    _require(
        record.get("schema") == "native-v3-real-e2e-evidence.v1",
        "Unexpected case evidence version",
    )
    case_id = record.get("case_id")
    _require(_registered_id(registry, case_id), "Unknown V3 acceptance case ID")
    api = record.get("api")
    _require(type(api) is int and api in APIS, "Invalid Android API target")
    _require(
        isinstance(record.get("receipt_id"), str)
        and re.fullmatch(r"[a-zA-Z0-9_-]{18,128}", record["receipt_id"]) is not None,
        "Receipt ID malformed",
    )
    _require(
        _git(expected_source_sha)
        and _git(expected_git_tree)
        and record.get("source_git_sha") == expected_source_sha
        and record.get("source_git_tree") == expected_git_tree,
        "Source SHA / tested tree not independently pinned",
    )
    _require(
        _sha(record.get("installed_apk_sha256"))
        and _sha(record.get("independent_fixture_sha256")),
        "Binary signing identities/hashes unavailable",
    )
    executed_at = record.get("executed_at_ms")
    _require(
        type(executed_at) is int
        and type(now_seconds) is int
        and abs(now_seconds * 1000 - executed_at) <= 300000,
        "Case stale or impossible clock epoch",
    )
    environment = record.get("emulator")
    _require(
        isinstance(environment, dict)
        and environment.get("os_api") == api
        and environment.get("api_verified_by") == "ANDROID_FRAMEWORK"
        and environment.get("qemu") is True
        and environment.get("serial") == SERIALS[api]
        and isinstance(environment.get("owner_worktree"), str)
        and environment["owner_worktree"].startswith("native-v3-")
        and isinstance(environment.get("boot_id"), str)
        and BOOT_ID.fullmatch(environment["boot_id"]) is not None,
        "No verified exclusively owned QEMU Android identity",
    )
    session = record.get("session")
    _require(
        isinstance(session, dict)
        and session.get("auth_result") == "MUTUAL_TLS_PAIRED"
        and _sha(session.get("paired_host_fingerprint"))
        and session.get("boot_id") == environment["boot_id"]
        and isinstance(session.get("principal_id"), str)
        and session["principal_id"].startswith("host:")
        and session.get("scope")
        in ("read", "status", "user_consented", "approved_control"),
        "Real Host/Native scoped mTLS pairing or boot epoch missing",
    )
    if case_id.startswith("V3-N03-"):
        _require(
            session["scope"] == "read", "Build/system snapshot requires paired read"
        )
    request = record.get("mcp_request")
    response = record.get("mcp_response")
    _require(
        isinstance(request, dict)
        and isinstance(response, dict)
        and request.get("executor") == "NATIVE_APK"
        and request.get("protocol") == "mcp_streamable_http"
        and request.get("method") in ALLOWED_SOURCE_METHODS
        and _sha(request.get("args_sha256"))
        and isinstance(request.get("tool"), str)
        and bool(re.fullmatch(r"native_[a-z_]{2,90}", request["tool"]))
        and isinstance(request.get("message_id"), str)
        and bool(re.fullmatch(r"[A-Za-z0-9_-]{3,90}", request["message_id"])),
        "No bounded actual MCP Tool call from installed Native APK",
    )
    _require(
        response.get("message_id") == request["message_id"]
        and response.get("is_error") is False
        and response.get("result_kind") == "ANDROID_FRAMEWORK_READ"
        and _sha(response.get("result_sha256")),
        "MCP reply is not a truthful Android API result",
    )
    callback = record.get("android_callback")
    _require(
        isinstance(callback, dict)
        and callback.get("package") == "org.androidmcp.nativeapp"
        and callback.get("invocation_id") == request["message_id"]
        and isinstance(callback.get("api_name"), str)
        and callback["api_name"].startswith("android.")
        and callback.get("caller_pid") == callback.get("android_pid")
        and type(callback.get("android_pid")) is int
        and callback["android_pid"] > 1000
        and _sha(callback.get("result_sha256"))
        and callback["result_sha256"] == response["result_sha256"],
        "Android framework callback not causally linked to Native Tool",
    )
    callback_time = callback.get("time_ms")
    _require(
        type(callback_time) is int
        and executed_at <= callback_time <= executed_at + 15000,
        "Android callback outside bounded request window",
    )
    oracle = record.get("oracle")
    _require(
        isinstance(oracle, dict)
        and oracle.get("observer_app") == "org.androidmcp.v3fixture"
        and oracle.get("observer_role") == "INDEPENDENT_ANDROID_OS_FIXTURE"
        and type(oracle.get("observer_pid")) is int
        and oracle["observer_pid"] != callback["android_pid"]
        and oracle.get("independent_observer_boot_id") == environment["boot_id"]
        and oracle.get("observed_android_api") == api
        and oracle.get("linked_invocation_id") == request["message_id"]
        and oracle.get("causality") == "NATIVE_FRAMEWORK_CALLBACK"
        and oracle.get("observed") is True
        and _sha(oracle.get("measurement_before_sha256"))
        and _sha(oracle.get("measurement_after_sha256"))
        and oracle.get("observed_result_sha256") == callback["result_sha256"],
        "Independent OS/fixture oracle missing or disagrees with Android callback",
    )
    observed_at = oracle.get("time_ms")
    _require(
        type(observed_at) is int
        and callback_time <= observed_at <= callback_time + 15000,
        "OS side-effect oracle was not after actual callback",
    )
    negatives = record.get("negative_recovery")
    _require(
        isinstance(negatives, dict) and set(negatives) == NEGATIVE_KEYS,
        "Incomplete refusal, Stop, timeout, crash or recovery matrix",
    )
    for scenario, evidence in negatives.items():
        _require(
            isinstance(evidence, dict)
            and evidence.get("status") == "PASS_REAL_ANDROID_NEGATIVE"
            and evidence.get("observer_role") == "INDEPENDENT_ANDROID_OS_FIXTURE"
            and evidence.get("android_api") == api
            and _sha(evidence.get("evidence_sha256")),
            f"Scenario {scenario} needs actual hashed independent Android evidence",
        )
    artifact = record.get("artifact")
    _require(
        isinstance(artifact, dict)
        and artifact.get("executor") == "NATIVE_APK"
        and artifact.get("production_sensitive_data") is False
        and artifact.get("bounded") is True
        and artifact.get("cleanup_released") is True,
        "No bounded, cleaned, synthetic-only fixture artifact receipt",
    )
    author = record.get("collected_by")
    _require(
        isinstance(author, str) and author.startswith("dev:"),
        "No attributable test-run collector",
    )
    review = record.get("review")
    _require(
        isinstance(review, dict)
        and review.get("schema") == "native-v3-evidence-review.v1"
        and review.get("role") == "INDEPENDENT_EVIDENCE_REVIEW"
        and review.get("decision") == "ACCEPT_CASE_EVIDENCE_NOT_FEATURE_RELEASE"
        and review.get("reviewer_id") != author
        and isinstance(review.get("reviewer_id"), str)
        and review["reviewer_id"].startswith("external-")
        and type(review.get("review_time_ms")) is int
        and observed_at <= review["review_time_ms"] <= observed_at + 300000,
        "Independent evidence reviewer not separate or cannot be verified",
    )

    signed = canonical_payload(record)
    digest = hashlib.sha256(signed).hexdigest()
    _require(
        review.get("receipt_digest") == digest,
        "Independent review does not bind complete exact receipt",
    )
    oracle_key_id = oracle.get("key_id")
    review_key_id = review.get("key_id")
    _require(
        isinstance(oracle_key_id, str)
        and isinstance(review_key_id, str)
        and oracle_key_id != review_key_id,
        "Independent oracle and reviewer identities must differ",
    )
    oracle_key = oracle_roots.get(oracle_key_id)
    review_key = reviewer_roots.get(review_key_id)
    _require(oracle_key != review_key, "Oracle and reviewer must have distinct keys")
    _verify_signature(
        oracle_key, record["oracle_signature"], signed, "Android OS oracle"
    )
    review_payload = json.dumps(
        {key: value for key, value in review.items() if key != "signature"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    # No reviewer-private-key provisioning is built into this project.
    _verify_signature(
        review_key, review["signature"], review_payload, "Independent reviewer"
    )
    return {
        "case_id": case_id,
        "api": api,
        "receipt_id": record["receipt_id"],
        "case_integrity": "VALIDATED_AGAINST_CALLER_PINNED_INDEPENDENT_KEYS",
        "evidence": "CONDITIONAL_ATTESTED_CASE_NOT_PRODUCT_RELEASE",
        "feature_done": False,
        "production_security_released": False,
    }


def assess_case_matrix(
    receipts: list[tuple[dict[str, Any], dict[str, bytes], dict[str, bytes]]],
    registry: dict[str, Any],
    now_seconds: int,
    expected_source_sha: str,
    expected_git_tree: str,
) -> dict[str, Any]:
    _require(len(receipts) == 4, "All four Android APIs mandatory")
    valid = [
        assess_case(
            case,
            registry,
            oracle,
            review,
            now_seconds,
            expected_source_sha,
            expected_git_tree,
        )
        for case, oracle, review in receipts
    ]
    apis = [case["api"] for case in valid]
    names = [case["case_id"] for case in valid]
    receipts_ids = [case["receipt_id"] for case in valid]
    _require(
        set(apis) == set(APIS) and len(set(apis)) == 4,
        "Missing/replayed/duplicate API cannot pass",
    )
    _require(len(set(names)) == 1, "Different acceptance IDs cannot fill 4 API matrix")
    _require(
        len(set(receipts_ids)) == 4, "Replay of a single receipt is not four tests"
    )
    return {
        "apis": sorted(apis),
        "passed_cases": 1,
        "source_class": "CONDITIONAL_EXTERNAL_ROOT_TEST_ONLY",
        "features_done": 0,
        "production_release_approvals": 0,
        "product_status": "PRODUCT_INCOMPLETE",
    }

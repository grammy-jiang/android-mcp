import copy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from android_mcp_host.security.approvals import (
    ApprovalDenied,
    ApprovalVerifier,
    encode_signed_envelope_for_tests,
)


def _permit(*, key, now=1000, operator="physical-operator", device="ABC-1", digest="b" * 64):
    body = {
        "version": 1,
        "nonce": "a" * 32,
        "operator": operator,
        "device_id": device,
        "plan_digest": digest,
        "not_before": now - 10,
        "expires_at": now + 100,
    }
    return encode_signed_envelope_for_tests(body, key)


def _verifier(store, key, now=1000):
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return ApprovalVerifier({"physical-operator": raw}, store, clock=lambda: now)


def test_exact_signature_is_one_time_and_persists(store):
    private = Ed25519PrivateKey.generate()
    verifier = _verifier(store, private)
    grant = _permit(key=private)
    verifier.verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)
    with pytest.raises(ApprovalDenied, match="consumed"):
        verifier.verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)


def test_operator_key_is_not_available_in_verifier(store):
    private = Ed25519PrivateKey.generate()
    v = _verifier(store, private)
    assert all(not hasattr(k, "sign") for k in v._keys.values())


@pytest.mark.parametrize(
    "edit",
    [
        ("payload", "device_id", "OTHER"),
        ("payload", "plan_digest", "c" * 64),
        ("payload", "operator", "other-operator"),
        ("payload", "version", 2),
        ("payload", "nonce", "INVALID"),
        ("payload", "not_before", "abc"),
        ("payload", "expires_at", 1600),
    ],
)
def test_modified_signed_payload_cannot_authorize(store, edit):
    private = Ed25519PrivateKey.generate()
    grant = _permit(key=private)
    grant[edit[0]][edit[1]] = edit[2]
    with pytest.raises(ApprovalDenied):
        _verifier(store, private).verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)


def test_signed_grant_for_different_target_is_rejected(store):
    key = Ed25519PrivateKey.generate()
    grant = _permit(key=key)
    verifier = _verifier(store, key)
    for target, digest in [("OTHER", "b" * 64), ("ABC-1", "d" * 64)]:
        with pytest.raises(ApprovalDenied, match="different"):
            verifier.verify_and_consume(grant, device_id=target, plan_digest=digest)
    verifier.verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)


@pytest.mark.parametrize(
    "start,end,now",
    [(1200, 1300, 1000), (0, 999, 1000), (900, 1300, 1000), (1000, 1000, 1000)],
)
def test_invalid_window_does_not_authorize(store, start, end, now):
    private = Ed25519PrivateKey.generate()
    body = _permit(key=private)["payload"]
    body["not_before"] = start
    body["expires_at"] = end
    grant = encode_signed_envelope_for_tests(body, private)
    with pytest.raises(ApprovalDenied):
        _verifier(store, private, now=now).verify_and_consume(
            grant, device_id="ABC-1", plan_digest="b" * 64
        )


def test_invalid_envelope_and_signature_fail_closed(store):
    key = Ed25519PrivateKey.generate()
    base = _permit(key=key)
    verifier = _verifier(store, key)
    for value in (
        None,
        [],
        {},
        {"payload": base["payload"]},
        {"payload": base["payload"], "signature": "nonsense"},
        {"payload": base["payload"], "signature": "a" * 86},
        {**base, "unexpected": True},
    ):
        with pytest.raises(ApprovalDenied):
            verifier.verify_and_consume(value, device_id="ABC-1", plan_digest="b" * 64)


def test_wrong_public_key_rejects_valid_other_signature(store):
    verifier = _verifier(store, Ed25519PrivateKey.generate())
    grant = _permit(key=Ed25519PrivateKey.generate())
    with pytest.raises(ApprovalDenied, match="signature"):
        verifier.verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)


def test_keyring_cannot_be_empty(store):
    with pytest.raises(ValueError):
        ApprovalVerifier({}, store)


def test_reject_wrong_payload_shape_and_operator_identifier(store):
    key = Ed25519PrivateKey.generate()
    grant = _permit(key=key)
    for changes in ({"surprise": "field"}, {"operator": "!bad operator"}, {"device_id": 123}):
        changed = copy.deepcopy(grant)
        changed["payload"].update(changes)
        with pytest.raises(ApprovalDenied):
            _verifier(store, key).verify_and_consume(
                changed, device_id="ABC-1", plan_digest="b" * 64
            )


def test_test_signing_helper_rejects_objects_without_sign_method():
    with pytest.raises(TypeError):
        encode_signed_envelope_for_tests({}, object())


def test_bad_base64_is_wrapped_as_denial(monkeypatch, store):
    private = Ed25519PrivateKey.generate()
    grant = _permit(key=private)

    def bad_decode(*args):
        raise ValueError("bad decoder")

    monkeypatch.setattr("android_mcp_host.security.approvals.base64.urlsafe_b64decode", bad_decode)
    with pytest.raises(ApprovalDenied, match="Malformed"):
        _verifier(store, private).verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)


def test_reject_overlong_canonical_approval(monkeypatch, store):
    import android_mcp_host.security.approvals as approvals

    private = Ed25519PrivateKey.generate()
    grant = _permit(key=private)
    monkeypatch.setattr(approvals, "_canonical", lambda data: b"x" * 4096)
    with pytest.raises(ApprovalDenied, match="too large"):
        _verifier(store, private).verify_and_consume(grant, device_id="ABC-1", plan_digest="b" * 64)

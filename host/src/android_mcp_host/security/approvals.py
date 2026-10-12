"""Verify external Ed25519 operator grants for exact device/action fingerprints.

Only public keys are stored by the Host. The *private signing key* must reside
outside both MCP runtimes and must never be reachable through Binnacle shells.
This API verifies trusted grants; it deliberately exposes no MCP approval tool.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from android_mcp_host.security.store import StateStore

_HEX = re.compile(r"[a-f0-9]{64}\Z")
_NONCE = re.compile(r"[a-f0-9]{32}\Z")
_OPERATOR = re.compile(r"[A-Za-z0-9_.@-]{1,100}\Z")
_REQUIRED = {"version", "nonce", "device_id", "plan_digest", "operator", "not_before", "expires_at"}


class ApprovalDenied(Exception):
    """A failed grant check never authorizes a device operation."""


def _canonical(body: Mapping[str, object]) -> bytes:
    return json.dumps(
        body, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _decode_signature(value: str) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != 86
        or not re.fullmatch(r"[A-Za-z0-9_-]{86}", value)
    ):
        raise ApprovalDenied("Malformed approval signature")
    try:
        raw = base64.urlsafe_b64decode(value + "==")
    except (ValueError, binascii.Error) as error:
        raise ApprovalDenied("Malformed approval signature") from error
    if len(raw) != 64 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise ApprovalDenied("Noncanonical approval signature")
    return raw


class ApprovalVerifier:
    """Check a trusted inbox envelope, and consume it atomically once."""

    def __init__(
        self,
        public_keys: Mapping[str, bytes],
        store: StateStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not public_keys:
            raise ValueError("At least one trusted operator public key is required")
        self._keys = {
            operator: Ed25519PublicKey.from_public_bytes(public)
            for operator, public in public_keys.items()
        }
        self._store = store
        self._clock = clock

    def verify_and_consume(self, envelope: object, *, device_id: str, plan_digest: str) -> None:
        """Consume a signed permit. Never accept the envelope as a MCP argument."""
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
            raise ApprovalDenied("Malformed approval envelope")
        body = envelope["payload"]
        if not isinstance(body, dict) or set(body) != _REQUIRED:
            raise ApprovalDenied("Malformed approval payload")
        if type(body["version"]) is not int or body["version"] != 1:
            raise ApprovalDenied("Unsupported approval version")
        operator = body["operator"]
        if not isinstance(operator, str) or not _OPERATOR.fullmatch(operator):
            raise ApprovalDenied("Invalid operator")
        public = self._keys.get(operator)
        if public is None:
            raise ApprovalDenied("Untrusted operator")
        nonce, digest = body["nonce"], body["plan_digest"]
        if (
            not isinstance(nonce, str)
            or not _NONCE.fullmatch(nonce)
            or not isinstance(digest, str)
            or not _HEX.fullmatch(digest)
        ):
            raise ApprovalDenied("Invalid permit identifier or digest")
        if not isinstance(body["device_id"], str) or len(body["device_id"]) > 128:
            raise ApprovalDenied("Invalid permit device")
        if body["device_id"] != device_id or digest != plan_digest:
            raise ApprovalDenied("Approval is for a different device or action")
        start, end = body["not_before"], body["expires_at"]
        if type(start) is not int or type(end) is not int or end <= start or end - start > 300:
            raise ApprovalDenied("Invalid approval expiry")
        now = self._clock()
        if not start <= now <= end:
            raise ApprovalDenied("Approval is not valid at this time")
        raw = _canonical(body)
        if len(raw) > 2048:
            raise ApprovalDenied("Approval payload too large")
        sig = _decode_signature(envelope["signature"])
        try:
            public.verify(sig, raw)
        except InvalidSignature as error:
            raise ApprovalDenied("Approval signature rejected") from error
        if not self._store.consume_grant(nonce, digest):
            raise ApprovalDenied("Approval was already consumed")


def encode_signed_envelope_for_tests(body: dict[str, object], signer: object) -> dict[str, object]:
    """Pure helper used only in unit tests; production never stores the signing key."""
    # Kept separate from ApprovalVerifier: no signer is constructed there.
    if not hasattr(signer, "sign"):
        raise TypeError("Test signer must implement sign")
    signature = signer.sign(_canonical(body))
    return {"payload": body, "signature": base64.urlsafe_b64encode(signature).decode().rstrip("=")}

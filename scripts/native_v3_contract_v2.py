"""Strict E02.b C0 candidate wire parser, not a grant/consent authority.

This source-auditable Python reference is a schema+context preflight only.
A valid frame never creates, authenticates, or authorizes a live MCP session.
Production admission must check the actual TLS peer, Android OS callbacks,
consent, durable replay journal and Native fencing before tool execution.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

FRAME_MAX_BYTES = 8192
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts/v2/native-security-envelope.v2.schema.json"
)
MAX_VALIDITY_MS = {
    "pair_challenge": 15000,
    "pair_proof": 15000,
    "session_authorization": 60000,
    "operation_grant": 15000,
    "lease_acquire": 15000,
    "lease_receipt": 30000,
}


class ContractError(ValueError):
    """Untrusted C0 candidate security frame denied before any side effect."""


@dataclass(frozen=True)
class ParsedFrame:
    raw: dict[str, Any]
    kind: str
    session_id: str
    authorized: bool = False
    consent_verified: bool = False
    lease_held: bool = False
    product_complete: bool = False

    def __repr__(self) -> str:
        return (
            "ParsedFrame(kind="
            + repr(self.kind)
            + ", session_id=[REDACTED], privileged=false)"
        )


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_frame(
    obj: Any,
    *,
    now_ms: int,
    expected_host_sha: str,
    expected_native_sha: str,
    expected_boot: str,
) -> ParsedFrame:
    if not isinstance(obj, dict):
        raise ContractError("V2 object required")
    # Bound in-memory object too; callers must not bypass parse_frame budget.
    try:
        size = len(json.dumps(obj, ensure_ascii=True).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("V2 frame cannot be safely encoded") from exc
    if size > FRAME_MAX_BYTES:
        raise ContractError("V2 frame exceeds byte budget")
    failures = sorted(
        _validator().iter_errors(obj), key=lambda err: tuple(map(str, err.path))
    )
    if failures:
        raise ContractError("V2 wire structure denied: " + failures[0].message[:170])
    if isinstance(now_ms, bool) or not isinstance(now_ms, int):
        raise ContractError("Trusted clock unavailable")
    issued = obj["issued_at_unix_ms"]
    expiry = obj["expires_at_unix_ms"]
    kind = obj["kind"]
    if not (
        issued <= now_ms <= expiry and 0 < expiry - issued <= MAX_VALIDITY_MS[kind]
    ):
        raise ContractError("Expired, future, or excessive v2 wire TTL")
    if (
        obj["host_spki_sha256"] != expected_host_sha
        or obj["native_spki_sha256"] != expected_native_sha
        or obj["native_boot_epoch"] != expected_boot
    ):
        raise ContractError("Bound Host/Native boot or public key context differs")
    payload = obj["payload"]
    if (
        kind == "session_authorization"
        and payload["tls_peer_spki_sha256"] != expected_host_sha
    ):
        raise ContractError("Authenticated TLS peer not bound to declared Host")
    # Deliberately do not interpret claims as proof of signatures, OS consent,
    # scope, lease, authorization or revocation. Those gates belong to E02.c–f.
    return ParsedFrame(
        raw=copy.deepcopy(obj),
        kind=kind,
        session_id=obj["session_id"],
    )


def encode_frame(parsed: ParsedFrame) -> str:
    if not isinstance(parsed, ParsedFrame) or any(
        (
            parsed.authorized,
            parsed.consent_verified,
            parsed.lease_held,
            parsed.product_complete,
        )
    ):
        raise ContractError("Cannot serialize a claimed authorized structural frame")
    text = json.dumps(
        parsed.raw, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(text.encode("utf-8")) > FRAME_MAX_BYTES:
        raise ContractError("V2 frame output exceeds byte budget")
    return text


def _no_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for name, value in items:
        if name in obj:
            raise ContractError("Duplicate v2 wire key forbidden")
        obj[name] = value
    return obj


def _no_js_special(number: str) -> Any:
    raise ContractError("Nonfinite JSON values forbidden in security wire")


def parse_frame(
    data: bytes,
    *,
    now_ms: int,
    expected_host_sha: str,
    expected_native_sha: str,
    expected_boot: str,
) -> ParsedFrame:
    if not isinstance(data, bytes) or not 0 < len(data) <= FRAME_MAX_BYTES:
        raise ContractError("Missing/unbounded v2 wire frame")
    try:
        decoded = data.decode("utf-8", "strict")
        obj = json.loads(
            decoded,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_no_js_special,
        )
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        raise ContractError("Invalid v2 JSON encoding") from exc
    return validate_frame(
        obj,
        now_ms=now_ms,
        expected_host_sha=expected_host_sha,
        expected_native_sha=expected_native_sha,
        expected_boot=expected_boot,
    )

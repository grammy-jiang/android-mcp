"""H5.c finite private synthetic Perfetto-shaped trace parsing and safe replies.

Not an implementation of Perfetto/trace_processor or binary .pftrace. The
fixed test protocol can produce only synthetic, numeric sanitized records.
No Host/Android-provided strings survive in the private output or MCP reply.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_RAW_BYTES = 131072
MAX_SANITIZED_BYTES = 32768
MAX_SAMPLES = 128
MAX_DURATION_S = 10
TRACE_VERSION = "mcp-synthetic-perfetto-v1"
MARKER = b"MCP_SYNTHETIC_TRACE_V1\n"
PROFILES = frozenset({"sched-lite-v1", "frames-lite-v1"})
_EVENTS = {
    "sched-lite-v1": frozenset({"cpu_slice", "sched_switch", "counter"}),
    "frames-lite-v1": frozenset({"frame_present", "frame_dropped", "counter"}),
}
_RECORD = re.compile(
    rb"ts_ms=(?:0|[1-9][0-9]{0,5});event=([a-z_]{3,24});value=(?:0|[1-9][0-9]{0,7})\Z"
)
_NUMBER = re.compile(rb"(?:0|[1-9][0-9]{0,7})\Z")
_ERRORS = {
    "INVALID_ACTION": "Only synthetic trace plan, capture or cancel are supported",
    "INVALID_INPUT": "Invalid finite synthetic trace selectors",
    "INVALID_PROFILE": "Requested Perfetto fixture profile is not fixed or supported",
    "NOT_OWNED": "Exact disposable emulator ownership is unavailable",
    "NOT_DEBUGGABLE": "Test-only debuggable state not independently verified",
    "TRACE_UNSUPPORTED": "Synthetic Perfetto trace support is not confirmed",
    "UNVERIFIED_TARGET": "Exact verified synthetic emulator lifecycle not available",
    "CONSENT_REQUIRED": "Independent expiring synthetic trace approval is absent",
    "EXECUTION_DISABLED": "Real Android Perfetto tracing remains disabled",
    "RECOVERY_REQUIRED": "Trace job is incomplete or uncertain and needs reconciliation",
    "JOB_UNAVAILABLE": "Private durable trace job is unavailable",
    "IDEMPOTENCY_CONFLICT": "Trace request conflicts with previously recorded parameters",
    "BAD_FRAME": "Synthetic trace identity or provenance did not match",
    "BAD_TRACE": "Synthetic trace content was malformed or unsanitizable",
    "TRACE_TOO_LARGE": "Synthetic trace exceeded fixed size bounds",
    "TIMEOUT": "Trace fixture timed out; outcome is uncertain",
    "CANCELLED": "Synthetic capture cancelled; no confirmed trace produced",
    "RUNNER_FAILED": "Private fixture, job or artifact operation failed",
    "ARTIFACT_EXPIRED": "Verified private synthetic trace or receipt has expired",
    "NOT_ACTIVE": "No exact active trace job can be cancelled",
}


class InvalidTrace(ValueError):
    """Only typed, bounded synthetic trace failures may reach the MCP boundary."""


def valid_capture(profile: object, duration_s: object, max_bytes: object, ttl_s: object) -> bool:
    return (
        type(profile) is str
        and profile in PROFILES
        and type(duration_s) is int
        and 1 <= duration_s <= MAX_DURATION_S
        and type(max_bytes) is int
        and 1024 <= max_bytes <= MAX_RAW_BYTES
        and type(ttl_s) is int
        and 1 <= ttl_s <= 300
    )


def plan_digest(
    handle: str,
    lid: str,
    request_id: str,
    profile: str,
    duration_s: int,
    max_bytes: int,
    ttl_s: int,
) -> str:
    content = {
        "purpose": TRACE_VERSION,
        "target": handle,
        "lifecycle": lid,
        "request": request_id,
        "profile": profile,
        "duration_s": duration_s,
        "max_bytes": max_bytes,
        "ttl_s": ttl_s,
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def sanitize_trace(
    raw: object,
    *,
    profile: str,
    duration_s: int,
    max_bytes: int,
) -> tuple[bytes, int, int]:
    """Drop unknown data, store *only* known numeric fixture trace records."""
    if (
        type(raw) is not bytes
        or not valid_capture(profile, duration_s, max_bytes, 1)
        or not len(MARKER) < len(raw) <= max_bytes
        or not raw.startswith(MARKER)
    ):
        raise InvalidTrace("Invalid finite synthetic trace envelope")
    if not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw:
        raise InvalidTrace("Control or unterminated synthetic trace")
    try:
        raw.decode("utf-8", "strict")
    except UnicodeError as error:
        raise InvalidTrace("Invalid trace UTF-8") from error
    rows = raw[len(MARKER) :].split(b"\n")[:-1]
    if not rows or len(rows) > MAX_SAMPLES * 2:
        raise InvalidTrace("Too many trace lines")
    kept: list[dict[str, int | str]] = []
    removed = 0
    previous_timestamp = -1
    for row in rows:
        if len(row) > 160 or any(byte < 32 or byte == 127 for byte in row):
            raise InvalidTrace("Unsafe trace line")
        match = _RECORD.fullmatch(row)
        if match is None:
            removed += 1
            continue
        timestamp = int(row.split(b";", 1)[0][6:])
        value = int(row.rsplit(b"=", 1)[1])
        event = match.group(1).decode("ascii")
        if (
            event not in _EVENTS[profile]
            or timestamp < previous_timestamp
            or timestamp > duration_s * 1000
            or value > 1000000
        ):
            raise InvalidTrace("Untrusted synthetic trace sequence")
        if len(kept) == MAX_SAMPLES:
            removed += 1
            continue
        previous_timestamp = timestamp
        kept.append({"ts_ms": timestamp, "event": event, "value": value})
    if not kept:
        raise InvalidTrace("No allowed synthetic trace events")
    serialized = json.dumps(
        {
            "format": TRACE_VERSION,
            "profile": profile,
            "requested_duration_s": duration_s,
            "synthetic_fixture_only": True,
            "samples": kept,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    if len(serialized) > MAX_SANITIZED_BYTES:
        raise InvalidTrace("Sanitized synthetic trace overflow")
    return serialized, len(kept), removed


def valid_sanitized_trace(raw: object, *, profile: str, duration_s: int) -> bool:
    """Verify persisted trace structure independently before receipt replay."""
    if type(raw) is not bytes or len(raw) > MAX_SANITIZED_BYTES:
        return False
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "format",
            "profile",
            "requested_duration_s",
            "synthetic_fixture_only",
            "samples",
        }:
            return False
        if (
            data["format"] != TRACE_VERSION
            or data["profile"] != profile
            or data["requested_duration_s"] != duration_s
            or data["synthetic_fixture_only"] is not True
            or type(data["samples"]) is not list
            or not 1 <= len(data["samples"]) <= MAX_SAMPLES
        ):
            return False
        last = -1
        for sample in data["samples"]:
            if type(sample) is not dict or set(sample) != {"ts_ms", "event", "value"}:
                return False
            ts, event, value = sample["ts_ms"], sample["event"], sample["value"]
            if (
                type(ts) is not int
                or not 0 <= ts <= duration_s * 1000
                or ts < last
                or type(event) is not str
                or event not in _EVENTS[profile]
                or type(value) is not int
                or not 0 <= value <= 1000000
            ):
                return False
            last = ts
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii") == raw
    except (TypeError, ValueError, KeyError, UnicodeError, OverflowError):
        return False


def reply(
    status: str,
    *,
    state: str = "none",
    name: str | None = None,
    handle: str | None = None,
    lifecycle: str | None = None,
    profile: str | None = None,
    duration_s: int | None = None,
    max_bytes: int | None = None,
    job_id: str | None = None,
    artifact_handle: str | None = None,
    receipt_handle: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    sample_count: int | None = None,
    redacted_lines: int | None = None,
    ttl_s: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "trace_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle,
        "profile": profile,
        "duration_s": duration_s,
        "max_bytes": max_bytes,
        "job_id": job_id,
        "artifact_handle": artifact_handle,
        "receipt_handle": receipt_handle,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "sample_count": sample_count,
        "redacted_lines": redacted_lines,
        "retention_seconds": ttl_s,
        "mime_type": "application/json",
        "format": TRACE_VERSION,
        "synthetic_fixture_only": True,
        "real_perfetto_enabled": False,
        "physical_device_reads_enabled": False,
        "raw_trace_returned": False,
        "privacy_class": "sensitive_private",
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }

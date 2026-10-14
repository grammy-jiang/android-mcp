"""H5.b finite synthetic Logcat policy; no real ADB streaming or raw output."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from android_mcp_host.logcat_filters import _LINE
from android_mcp_host.ui_action_support import valid_lifecycle_job, valid_request_id

MAX_RAW_BYTES = 65536
MAX_EVENTS = 128
MAX_PAGE_SIZE = 16
MAX_TTL_SECONDS = 120
MAX_MESSAGE_BYTES = 160
TAGS = frozenset({"McpTest", "ActivityManager", "System"})
_SAFE = re.compile(
    r"(?:STATE=(?:ready|running|idle|stopped)|EVENT=(?:start|stop|connected|disconnected)"
    r"|UPTIME_SECONDS=[0-9]{1,8}|BATTERY_PERCENT=(?:100|[0-9]{1,2}))\Z",
    re.ASCII,
)
ERRORS = {
    "INVALID_ACTION": "Unknown bounded synthetic Logcat action",
    "INVALID_INPUT": "Invalid owner-pinned Logcat request or limits",
    "INVALID_TAG": "Unsupported fixed synthetic Logcat tag",
    "NOT_OWNED": "Exact private synthetic emulator ownership required",
    "CONSENT_REQUIRED": "Independent expiring synthetic Logcat approval missing",
    "EXECUTION_DISABLED": "No production Logcat streaming reader is enabled",
    "UNVERIFIED_TARGET": "Exact synthetic emulator lifecycle not verified",
    "JOB_UNAVAILABLE": "Durable private stream job unavailable",
    "IDEMPOTENCY_CONFLICT": "Conflicting request parameters cannot be replayed",
    "RECOVERY_REQUIRED": "Previous job is incomplete or has uncertain state",
    "INVALID_FRAME": "Synthetic frame identity or completion invalid",
    "INVALID_LOGCAT": "Unsafe or invalid synthetic Logcat input",
    "OUTPUT_LIMIT": "Synthetic Logcat input exceeds finite capture cap",
    "TIMEOUT": "Synthetic Logcat capture deadline exceeded",
    "RUNNER_FAILED": "Synthetic Logcat reader or private persistence failed",
    "CURSOR_CONFLICT": "Cursor is stale, invalid or was already consumed",
    "EXPIRED": "Private synthetic stream lease expired",
    "STOPPED": "Synthetic Logcat stream is stopped",
    "ENDED": "Synthetic Logcat stream is already fully consumed",
    "NOT_FOUND": "Exact private stream job not found",
    "CANCELLED": "Synthetic stream capture was cancelled or uncertain",
}


class InvalidSyntheticLogcat(ValueError):
    """Untrusted raw synthetic frame cannot be admitted."""


def valid_request(
    action: object,
    lifecycle: object,
    request: object,
    job: object,
    cursor: object,
    tag: object,
    page_size: object,
    max_events: object,
    ttl: object,
) -> str | None:
    if action not in ("plan", "start", "poll", "stop"):
        return "INVALID_ACTION"
    if (
        not valid_lifecycle_job(lifecycle)
        or (action != "plan" and not valid_request_id(request))
        or (action in ("poll", "stop") and not valid_lifecycle_job(job))
        or (action == "poll" and (not isinstance(cursor, str) or len(cursor) > 160))
        or (action != "poll" and cursor is not None)
        or (action in ("plan", "start") and job is not None)
        or type(page_size) is not int
        or not 1 <= page_size <= MAX_PAGE_SIZE
        or type(max_events) is not int
        or not 1 <= max_events <= MAX_EVENTS
        or type(ttl) is not int
        or not 1 <= ttl <= MAX_TTL_SECONDS
    ):
        return "INVALID_INPUT"
    if tag is not None and (type(tag) is not str or tag not in TAGS):
        return "INVALID_TAG"
    return None


def digest(
    handle: str, lifecycle: str, request: str, tag: str | None, maximum: int, ttl: int
) -> str:
    data = json.dumps(
        {
            "purpose": "h5b-synthetic-stream-v1",
            "handle": handle,
            "lifecycle": lifecycle,
            "request": request,
            "tag": tag,
            "maximum": maximum,
            "ttl": ttl,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def parse_events(
    payload: object, *, tag: str | None, maximum: int
) -> tuple[list[dict[str, str]], int, bool]:
    """Redact on strict allowlist BEFORE SQLite storage; never log raw bytes."""
    if type(payload) is not bytes:
        raise InvalidSyntheticLogcat("Invalid raw stream payload type")
    if len(payload) > MAX_RAW_BYTES:
        raise InvalidSyntheticLogcat("Synthetic stream size limit exceeded")
    try:
        raw = payload.decode("utf-8", "strict")
    except UnicodeError as error:
        raise InvalidSyntheticLogcat("Invalid UTF-8 synthetic stream") from error
    if "\x00" in raw or "\r" in raw or "\ufeff" in raw:
        raise InvalidSyntheticLogcat("Unsafe synthetic stream control characters")
    events: list[dict[str, str]] = []
    dropped = 0
    for line in raw.splitlines():
        if len(line) > 1024 or any(ord(c) < 32 or ord(c) > 126 for c in line):
            dropped += 1
            continue
        match = _LINE.fullmatch(line)
        if match is None:
            dropped += 1
            continue
        priority, found_tag, message = match.groups()
        if found_tag not in TAGS:
            dropped += 1
            continue
        if tag is not None and found_tag != tag:
            continue
        if len(events) >= maximum:
            dropped += 1
            continue
        # Unknown log content, including structured secrets, never survives.
        safe = (
            message
            if len(message) <= MAX_MESSAGE_BYTES and _SAFE.fullmatch(message)
            else "[REDACTED]"
        )
        events.append({"priority": priority, "tag": found_tag, "message": safe})
    if payload and not events and tag is None:
        raise InvalidSyntheticLogcat("No valid synthetic log records")
    return events, dropped, dropped > 0


def valid_stored_events(value: object) -> bool:
    """Validate every persisted entry again at the MCP disclosure boundary."""
    if type(value) is not list or len(value) > MAX_EVENTS:
        return False
    for event in value:
        if type(event) is not dict or set(event) != {"priority", "tag", "message"}:
            return False
        priority, tag, message = event["priority"], event["tag"], event["message"]
        if (
            type(priority) is not str
            or priority not in frozenset({"V", "D", "I", "W", "E", "F"})
            or type(tag) is not str
            or tag not in TAGS
            or type(message) is not str
            or len(message) > MAX_MESSAGE_BYTES
            or (message != "[REDACTED]" and _SAFE.fullmatch(message) is None)
        ):
            return False
    return True


def reply(
    status: str,
    state: str = "none",
    *,
    name: str | None = None,
    handle: str | None = None,
    lifecycle: str | None = None,
    job_id: str | None = None,
    cursor: str | None = None,
    entries: list[dict[str, str]] | None = None,
    from_index: int | None = None,
    next_index: int | None = None,
    total_events: int | None = None,
    dropped_events: int | None = None,
    truncated: bool = False,
    ttl: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "stream_state": state,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle,
        "job_id": job_id,
        "cursor": cursor,
        "entries": entries if entries is not None else [],
        "from_index": from_index,
        "next_index": next_index,
        "total_events": total_events,
        "dropped_events": dropped_events,
        "truncated": truncated,
        "retention_seconds": ttl,
        "privacy_class": "sensitive_private",
        "synthetic_fixture_only": True,
        "real_logcat_stream_enabled": False,
        "physical_device_reads_enabled": False,
        "raw_logcat_returned": False,
        "errors": [{"code": error, "message": ERRORS[error]}] if error else [],
    }

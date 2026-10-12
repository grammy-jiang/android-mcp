"""Finite, privacy-redacted, device-pinned Logcat snapshots with fixed CLI argv.

No arbitrary shell command or file path, no default target, and no mutation.
The existing adb_develop logcat_snapshot v1 behavior is unchanged.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any

from android_mcp_host.adb import AdbClient
from android_mcp_host.command_runner import OutputLimitExceeded, completed_bounded
from android_mcp_host.device_guard import require_online, valid_device_id
from android_mcp_host.package_inspector import valid_package

OUTPUT_BYTES = 65536
MAX_LINES = 200
MAX_MESSAGE = 512
MAX_TOTAL_MESSAGE = 16000
_TIMEOUT = 5.0
_PRIORITY = "VDIWEF"
_TAG = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,31}\Z", re.ASCII)
_PID = re.compile(r"[1-9][0-9]{0,6}\Z", re.ASCII)
_LINE = re.compile(
    r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+\s+([VDIWEF])\s+([^:]{1,32}):\s?(.*)$",
    re.ASCII,
)
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[-_]?key|authorization|session[-_]?id)"
    r"\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_EMAIL = re.compile(r"(?i)\b[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
_MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
_LONG_ID = re.compile(r"(?i)\b(?:[0-9a-f]{24,}|[0-9]{10,15})\b")
Reader = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def get_logcat_output_schema() -> dict[str, Any]:
    """Read the Host-only packaged v1 Tool output contract."""
    schema: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-logcat-filters.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(schema, dict):
        raise ValueError("Invalid packaged Logcat output schema")
    return schema


def _read(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return completed_bounded(argv, timeout_s, OUTPUT_BYTES)


def _error(code: str) -> dict[str, str]:
    # Logcat and stderr are untrusted and can contain personal credentials.
    return {"code": code, "message": "Bounded Logcat observation was unavailable or incomplete"}


def _sanitize(text: str, device_id: str) -> str:
    """Redact recognized secrets/identifiers and all terminal control bytes."""
    cleaned = _ANSI.sub("", text)
    cleaned = "".join(character if 32 <= ord(character) <= 126 else " " for character in cleaned)
    if device_id:
        cleaned = cleaned.replace(device_id, "[DEVICE]")
    cleaned = _BEARER.sub("Bearer [REDACTED]", cleaned)
    cleaned = _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", cleaned)
    for pattern in (_EMAIL, _MAC, _IPV4, _LONG_ID):
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned[:MAX_MESSAGE]


def _records(
    text: str,
    *,
    device_id: str,
    tag: str | None,
    severity: str | None,
) -> tuple[list[dict[str, str]], bool]:
    entries: list[dict[str, str]] = []
    partial = False
    total = 0
    for raw in text.splitlines():
        if not raw:
            continue
        if "\ufffd" in raw:
            partial = True
            continue
        match = _LINE.fullmatch(raw)
        if match is None:
            partial = True
            continue
        priority, found_tag, message = match.groups()
        if _TAG.fullmatch(found_tag) is None:
            partial = True
            continue
        if tag is not None and found_tag != tag:
            continue
        if severity is not None and _PRIORITY.index(priority) < _PRIORITY.index(severity):
            continue
        if len(entries) == MAX_LINES or total >= MAX_TOTAL_MESSAGE:
            return entries, True
        clean = _sanitize(message, device_id)
        room = MAX_TOTAL_MESSAGE - total
        if len(clean) > room:
            clean = clean[:room]
            partial = True
        total += len(clean)
        if len(message) > MAX_MESSAGE:
            partial = True
        entries.append({"priority": priority, "tag": found_tag, "message": clean})
    return entries, partial


class LogcatFilters:
    """Allowlisted bounded snapshots only; no streaming or mutation surface."""

    def __init__(self, adb: AdbClient | None = None, *, reader: Reader = _read) -> None:
        self._adb = adb if adb is not None else AdbClient()
        self._reader = reader

    def capture(
        self,
        device_id: str,
        *,
        lines: int = 100,
        tag: str | None = None,
        package: str | None = None,
        severity: str | None = None,
        timeout_s: float = _TIMEOUT,
    ) -> dict[str, Any]:
        valid_id = valid_device_id(device_id)
        valid_tag = tag is None or (isinstance(tag, str) and _TAG.fullmatch(tag) is not None)
        valid_package_id = package is None or valid_package(package)
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id if valid_id else "",
            "status": "error",
            "filters": {
                "tag": tag if valid_tag else None,
                "package": package if valid_package_id else None,
                "severity": severity
                if isinstance(severity, str) and severity in _PRIORITY
                else None,
            },
            "entries": [],
            "truncated": False,
            "errors": [],
        }

        def fail(code: str, status: str = "error") -> dict[str, Any]:
            response["status"] = status
            response["errors"].append(_error(code))
            return response

        if not valid_id:
            return fail("INVALID_DEVICE_ID")
        if type(lines) is not int or not 10 <= lines <= MAX_LINES:
            return fail("INVALID_ARGUMENTS")
        if not valid_tag or not valid_package_id:
            return fail("INVALID_ARGUMENTS")
        if severity is not None and (not isinstance(severity, str) or severity not in _PRIORITY):
            return fail("INVALID_ARGUMENTS")
        if type(timeout_s) not in (int, float) or not 0.1 <= timeout_s <= 10.0:
            return fail("INVALID_ARGUMENTS")

        report = self._adb.inspect()
        problem = require_online(report, device_id)
        if problem is not None:
            return fail(problem["code"])
        if not report.executable:
            return fail("ADB_NOT_FOUND")

        def execute(argv: list[str]) -> subprocess.CompletedProcess[str] | str:
            try:
                result = self._reader(argv, timeout_s)
            except subprocess.TimeoutExpired:
                return "LOGCAT_TIMEOUT"
            except OutputLimitExceeded:
                return "OUTPUT_LIMIT"
            except PermissionError:
                return "PERMISSION_DENIED"
            except (OSError, ValueError, RuntimeError):
                return "LOGCAT_EXEC_FAILED"
            if (
                not isinstance(result.stdout, str)
                or not isinstance(result.stderr, str)
                or len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
                > OUTPUT_BYTES
            ):
                return "OUTPUT_LIMIT"
            return result

        pid_flag: list[str] = []
        if package is not None:
            pid_result = execute([report.executable, "-s", device_id, "shell", "pidof", package])
            if isinstance(pid_result, str):
                return fail(pid_result, "timeout" if pid_result == "LOGCAT_TIMEOUT" else "error")
            if pid_result.returncode != 0 or not pid_result.stdout.strip():
                return fail("PROCESS_NOT_RUNNING")
            if pid_result.stderr:
                return fail("PROCESS_UNKNOWN")
            pids = pid_result.stdout.strip().split()
            if len(pids) != 1 or _PID.fullmatch(pids[0]) is None:
                return fail("AMBIGUOUS_PROCESS")
            pid_flag = [f"--pid={pids[0]}"]

        # Logcat's own filters reduce exposure before parsing. The client has
        # no raw shell or executable field, and all dynamic values are checked.
        filterspec = (
            [f"{tag}:{severity or 'V'}", "*:S"]
            if tag is not None
            else ([f"*:{severity}"] if severity is not None else [])
        )
        argv = [
            report.executable,
            "-s",
            device_id,
            "logcat",
            "-d",
            "-t",
            str(lines),
            "-v",
            "threadtime",
            *pid_flag,
            *filterspec,
        ]
        result = execute(argv)
        if isinstance(result, str):
            status = "timeout" if result == "LOGCAT_TIMEOUT" else "partial"
            return fail(result, status)
        if result.returncode != 0:
            return fail("LOGCAT_FAILED")
        entries, partial = _records(result.stdout, device_id=device_id, tag=tag, severity=severity)
        response["entries"] = entries
        response["truncated"] = partial
        if partial or result.stderr:
            return fail("PARTIAL_DATA", "partial")
        response["status"] = "ok"
        return response

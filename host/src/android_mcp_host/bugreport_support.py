"""Bounded ZIP validation and strict allowlist redaction for fake bugreports.

No arbitrary archive member, binary diagnostic or raw report is persisted.
Only finite synthetic text fields are retained; unknown lines are replaced.
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
import zlib
from typing import Any

MAX_ZIP_BYTES = 1024 * 1024
MAX_MEMBER_BYTES = 32768
MAX_DECOMPRESSED_BYTES = 65536
MAX_LINES = 128
MAX_LINE_BYTES = 256
MAX_SANITIZED_BYTES = 65536
BUGREPORTZ_MARKER = "OK:/bugreports/bugreport-mcp-fixture.zip"
_VERSION = b"BUGREPORTV1\n"
_MEMBERS = ("version.txt", "bugreport.txt")
_ALLOWED = (
    re.compile(rb"UPTIME_SECONDS=(?:0|[1-9][0-9]{0,8})\Z"),
    re.compile(rb"BATTERY_PERCENT=(?:[0-9]|[1-9][0-9]|100)\Z"),
    re.compile(rb"STATE=(?:ready|idle|offline)\Z"),
)
_REDACTED = b"[REDACTED]"


class InvalidBugreport(ValueError):
    """Untrusted or non-sanitizable private synthetic diagnostics."""


def _sanitize_lines(raw: bytes) -> tuple[bytes, int]:
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise InvalidBugreport("Invalid diagnostic UTF-8") from error
    if not raw or not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw:
        raise InvalidBugreport("Malformed synthetic diagnostic lines")
    rows = raw.split(b"\n")[:-1]
    if not 1 <= len(rows) <= MAX_LINES:
        raise InvalidBugreport("Too many synthetic report lines")
    safe: list[bytes] = []
    removed = 0
    for line in rows:
        if len(line) > MAX_LINE_BYTES or any(byte < 32 or byte == 127 for byte in line):
            raise InvalidBugreport("Oversized or control-bearing diagnostics")
        if line == _REDACTED or any(pattern.fullmatch(line) for pattern in _ALLOWED):
            safe.append(line)
        else:
            safe.append(_REDACTED)
            removed += 1
    return b"\n".join(safe) + b"\n", removed


def _zip_pair(version: bytes, text: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in zip(_MEMBERS, (version, text), strict=True):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3
            entry.external_attr = 0o100600 << 16
            archive.writestr(entry, body)
    encoded = buffer.getvalue()
    if len(encoded) > MAX_SANITIZED_BYTES:
        raise InvalidBugreport("Sanitized bugreport size exceeded")
    return encoded


def sanitize_bugreport(raw: bytes) -> tuple[bytes, int]:
    """Only two literal synthetic members; sanitize *before* private put."""
    if type(raw) is not bytes or not 40 <= len(raw) <= MAX_ZIP_BYTES:
        raise InvalidBugreport("Invalid bounded bugreport archive size")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            entries = archive.infolist()
            if len(entries) != 2 or tuple(item.filename for item in entries) != _MEMBERS:
                raise InvalidBugreport("Untrusted bugreport ZIP members")
            expanded = 0
            for member in entries:
                if (
                    member.is_dir()
                    or member.flag_bits & 1
                    or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or stat.S_IFMT(member.external_attr >> 16) == stat.S_IFLNK
                    or member.file_size <= 0
                    or member.file_size > MAX_MEMBER_BYTES
                    or member.compress_size <= 0
                    or (member.file_size > 4096 and member.file_size / member.compress_size > 100)
                ):
                    raise InvalidBugreport("Untrusted bugreport archive entries")
                expanded += member.file_size
            if expanded > MAX_DECOMPRESSED_BYTES or archive.testzip() is not None:
                raise InvalidBugreport("Corrupt or oversized bugreport ZIP")
            version = archive.read(_MEMBERS[0])
            text = archive.read(_MEMBERS[1])
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, ValueError, zlib.error) as error:
        raise InvalidBugreport("Invalid synthetic bugreport ZIP") from error
    if version != _VERSION:
        raise InvalidBugreport("Missing synthetic bugreport version")
    sanitized, removed = _sanitize_lines(text)
    return _zip_pair(_VERSION, sanitized), removed


def verified_redacted_zip(raw: object) -> bool:
    if type(raw) is not bytes:
        return False
    try:
        sanitized, removed = sanitize_bugreport(raw)
        return sanitized == raw and removed == 0
    except InvalidBugreport:
        return False


def verify_bugreport_frame(
    frame: Any,
    *,
    expected_type: type[Any],
    name: str,
    handle: str,
    lifecycle: str,
) -> bool:
    return (
        type(frame) is expected_type
        and frame.avd_name == name
        and frame.avd_handle == handle
        and frame.lifecycle_job_id == lifecycle
        and frame.complete is True
        and frame.synthetic is True
        and frame.status_line == BUGREPORTZ_MARKER
        and type(frame.payload) is bytes
    )

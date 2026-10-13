"""Private artifact formats, input validation and safe filesystem primitives."""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import stat
import zipfile
from importlib.resources import files
from pathlib import Path
from typing import Any

MAX_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_RECORDS = 4096
MAX_TTL_S = 7 * 24 * 60 * 60
SCAN_LIMIT = 20000
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,63}\Z", re.ASCII)
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_HANDLE = re.compile(r"art_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_OBJECT = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SUPPORTED_MIMES = frozenset(
    {
        "application/octet-stream",
        "application/json",
        "text/plain",
        "application/zip",
        "application/vnd.android.package-archive",
        "application/vnd.android.aab",
        "application/pdf",
        "image/png",
        "image/jpeg",
    }
)


class ArtifactStoreError(Exception):
    """Fail-closed error with a stable reason, never user-provided content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Private artifact unavailable: {code}")


def get_artifact_metadata_schema() -> dict[str, Any]:
    result: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-private-artifact-metadata.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(result, dict):
        raise ValueError("Invalid packaged private artifact metadata schema")
    return result


def _private_directory(path: Path) -> None:
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ArtifactStoreError("UNTRUSTED_ROOT")
        path.mkdir(mode=0o700, exist_ok=True)
        current = path.stat()
        if (
            not stat.S_ISDIR(current.st_mode)
            or stat.S_IMODE(current.st_mode) != 0o700
            or current.st_uid != os.getuid()
        ):
            raise ArtifactStoreError("UNTRUSTED_ROOT")
    except OSError as error:
        raise ArtifactStoreError("UNTRUSTED_ROOT") from error


def _read_secret(path: Path) -> bytes:
    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        pass
    except OSError as error:
        raise ArtifactStoreError("UNTRUSTED_ROOT") from error
    else:
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise ArtifactStoreError("UNTRUSTED_ROOT") from error
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_nlink != 1
        ):
            raise ArtifactStoreError("UNTRUSTED_ROOT")
        value = path.read_bytes()
        if len(value) != 32:
            raise ArtifactStoreError("UNTRUSTED_ROOT")
        return value
    except OSError as error:
        raise ArtifactStoreError("UNTRUSTED_ROOT") from error


def _validate_mime(data: bytes, mime_type: str) -> None:
    if mime_type not in _SUPPORTED_MIMES:
        raise ArtifactStoreError("UNSUPPORTED_MIME")
    if mime_type == "application/octet-stream":
        return
    if mime_type == "image/png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif mime_type == "image/jpeg":
        valid = data.startswith(b"\xff\xd8\xff")
    elif mime_type == "application/pdf":
        valid = data.startswith(b"%PDF-")
    elif mime_type in {
        "application/zip",
        "application/vnd.android.package-archive",
        "application/vnd.android.aab",
    }:
        valid = data.startswith(b"PK\x03\x04") and zipfile.is_zipfile(io.BytesIO(data))
    else:
        try:
            text = data.decode("utf-8")
            valid = not any(ord(character) < 32 and character not in "\r\n\t" for character in text)
            if valid and mime_type == "application/json":
                json.loads(text)
        except (UnicodeError, ValueError):
            valid = False
    if not valid:
        raise ArtifactStoreError("MIME_MISMATCH")

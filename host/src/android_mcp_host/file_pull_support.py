"""H4.d exact synthetic app-export path, media and size policy.

No arbitrary device paths, globs, shell, host output filenames or real ADB.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from android_mcp_host.emulator_debug_support import valid_package

MAX_PULL_BYTES = 1024 * 1024
DEFAULT_PULL_BYTES = 262144
MAX_FILE_NAME = 64
_ALLOWED_SUFFIXES = {
    ".json": "application/json",
    ".txt": "text/plain",
    ".bin": "application/octet-stream",
}
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def valid_synthetic_package(package: object) -> bool:
    """Only operator-pinned synthetic test apps; never arbitrary user packages."""
    return (
        valid_package(package)
        and isinstance(package, str)
        and package.startswith("org.example.synthetic.")
    )


def approved_source(package: object, path: object) -> tuple[str, str] | None:
    """Return (filename, mime) only for a single app-owned export leaf.

    Parsing is lexical; real-device symlinks are never assumed safe. They are
    separately rejected by the synthetic frame contract.
    """
    if (
        not valid_synthetic_package(package)
        or not isinstance(path, str)
        or len(path) > 240
        or "\x00" in path
        or ".." in path
        or "\\" in path
    ):
        return None
    assert isinstance(package, str)
    prefix = f"/sdcard/Android/data/{package}/files/mcp-export/"
    if not path.startswith(prefix):
        return None
    filename = path[len(prefix) :]
    if _FILENAME.fullmatch(filename) is None:
        return None
    for suffix, mime in _ALLOWED_SUFFIXES.items():
        if filename.endswith(suffix):
            return filename, mime
    return None


def valid_digest(digest: Any) -> bool:
    return isinstance(digest, str) and _DIGEST.fullmatch(digest) is not None


def valid_limit(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_PULL_BYTES


def transfer_slot(lid: str, remote_path: str) -> str:
    digest = hashlib.sha256((lid + "\x00" + remote_path).encode("ascii")).hexdigest()
    return "h4d-export-" + digest[:32]


def transfer_digest(
    info: dict[str, Any],
    lid: str,
    path: str,
    request: str,
    expected_sha: str,
    mime: str,
    cap: int,
) -> str:
    plan = {
        "operation": "h4d-synthetic-private-file-pull-v1",
        "identity": info["handle"],
        "lifecycle": lid,
        "source_path_sha256": hashlib.sha256(path.encode("ascii")).hexdigest(),
        "request_id": request,
        "expected_sha256": expected_sha,
        "mime_type": mime,
        "max_bytes": cap,
    }
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()

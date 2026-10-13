"""Authenticated, bounded synthetic snapshot receipts for MCP-owned local AVDs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from android_mcp_host.avd_inventory_support import read_private

FORMAT_VERSION = 1
MAX_SNAPSHOTS_PER_AVD = 12
MAX_RECORD_BYTES = 4096
_SNAPSHOT = re.compile(r"snap_[A-Za-z0-9][A-Za-z0-9_-]{1,43}\Z", re.ASCII)
_HANDLE = re.compile(r"mcpsnap_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_KEYS = {
    "schema_version",
    "snapshot_version",
    "name",
    "avd_handle",
    "owner_ref",
    "snapshot_name",
    "snapshot_handle",
    "image_sha256",
    "api",
    "abi",
    "fixture_sha256",
    "signature",
}


def valid_snapshot(value: object) -> bool:
    return isinstance(value, str) and _SNAPSHOT.fullmatch(value) is not None


def snapshot_path(root: Path, avd_name: str, snapshot_name: str) -> Path:
    return root / f".mcp-snapshot-{avd_name}-{snapshot_name}.json"


def signed_snapshot_handle(secret: bytes, avd_handle: str, snapshot_name: str) -> str:
    digest = hmac.new(
        secret, f"h3d:{avd_handle}:{snapshot_name}".encode("ascii"), hashlib.sha256
    ).digest()[:24]
    return "mcpsnap_" + base64.urlsafe_b64encode(digest).decode("ascii")


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("ascii")


def signed_record(secret: bytes, avd: dict[str, Any], snapshot_name: str) -> dict[str, Any]:
    frame = {
        "fixture": "owned-synthetic-snapshot-v1",
        "avd_handle": avd["handle"],
        "snapshot_name": snapshot_name,
        "image_sha256": avd["artifact_sha256"],
    }
    data: dict[str, Any] = {
        "schema_version": 1,
        "snapshot_version": FORMAT_VERSION,
        "name": avd["name"],
        "avd_handle": avd["handle"],
        "owner_ref": avd["owner_ref"],
        "snapshot_name": snapshot_name,
        "snapshot_handle": signed_snapshot_handle(secret, avd["handle"], snapshot_name),
        "image_sha256": avd["artifact_sha256"],
        "api": avd["api"],
        "abi": avd["abi"],
        "fixture_sha256": hashlib.sha256(_canonical(frame)).hexdigest(),
    }
    data["signature"] = hmac.new(secret, _canonical(data), hashlib.sha256).hexdigest()
    return data


def verified_record(
    path: Path, secret: bytes, avd: dict[str, Any], snapshot_name: str
) -> dict[str, Any] | None:
    """Reject malformed, unexpected, symlinked or changed foreign snapshot records."""
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            return None
    except OSError:
        return None
    raw = read_private(path, MAX_RECORD_BYTES)
    if raw is None:
        return None
    try:
        candidate = json.loads(raw)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(candidate, dict) or set(candidate) != _KEYS:
        return None
    expected = signed_record(secret, avd, snapshot_name)
    signature = candidate.get("signature")
    if not isinstance(signature, str):
        return None
    if not hmac.compare_digest(signature, expected["signature"]):
        return None
    if candidate != expected:
        return None
    return expected


def public_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": record["snapshot_name"],
        "handle": record["snapshot_handle"],
        "image_sha256": record["image_sha256"],
        "api": record["api"],
        "abi": record["abi"],
        "snapshot_version": record["snapshot_version"],
        "fixture_sha256": record["fixture_sha256"],
    }

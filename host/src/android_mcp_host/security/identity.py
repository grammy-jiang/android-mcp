"""Canonical fingerprints for *already validated* device operation plans.

No MCP request may inject a custom digest, executable, or artifact hash.
Fingerprint values bind an external approval to the exact action and target.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence

_DEVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def fingerprint(
    *,
    device_id: str,
    kind: str,
    argv_suffix: Sequence[str],
    artifact_sha256: str | None = None,
) -> str:
    """Hash the full canonical plan, not the caller's description of it."""
    if not isinstance(device_id, str) or not _DEVICE.fullmatch(device_id):
        raise ValueError("Invalid device ID")
    if not isinstance(kind, str) or not kind or len(kind) > 64 or not kind.isascii():
        raise ValueError("Invalid action kind")
    if not isinstance(argv_suffix, (tuple, list)) or not argv_suffix:
        raise ValueError("Invalid command arguments")
    if any(not isinstance(a, str) or not a or "\x00" in a or len(a) > 8192 for a in argv_suffix):
        raise ValueError("Invalid command arguments")
    if artifact_sha256 is not None and (
        not isinstance(artifact_sha256, str) or not _DIGEST.fullmatch(artifact_sha256)
    ):
        raise ValueError("Invalid artifact digest")
    payload = {
        "v": 1,
        "device_id": device_id,
        "kind": kind,
        "argv": list(argv_suffix),
        "artifact_sha256": artifact_sha256,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

"""Strict destination and HMAC fixture policy; never real Android authorization."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from android_mcp_host.file_pull_support import valid_synthetic_package

MAX_PUSH_BYTES = 1024 * 1024
DEFAULT_PUSH_BYTES = 262144
_ALLOWED_SUFFIXES = {
    ".bin": "application/octet-stream",
    ".json": "application/json",
    ".txt": "text/plain",
}
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ART = re.compile(r"art_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)


def approved_destination(package: object, path: object) -> tuple[str, str] | None:
    """Only one literal ASCII leaf in an operator-pinned fake app import dir."""
    if (
        not valid_synthetic_package(package)
        or not isinstance(path, str)
        or len(path) > 240
        or ".." in path
        or "\\" in path
        or any(ord(ch) < 32 or ord(ch) > 126 for ch in path)
    ):
        return None
    assert isinstance(package, str)
    prefix = f"/sdcard/Android/data/{package}/files/mcp-import/"
    if not path.startswith(prefix):
        return None
    filename = path[len(prefix) :]
    if _NAME.fullmatch(filename) is None:
        return None
    for suffix, mime in _ALLOWED_SUFFIXES.items():
        if filename.endswith(suffix):
            return filename, mime
    return None


def valid_request(
    lid: object,
    artifact: object,
    sha: object,
    limit: object,
    action: str,
    request_id: object,
    job_id: object,
) -> bool:
    return (
        isinstance(lid, str)
        and _JOB.fullmatch(lid) is not None
        and isinstance(artifact, str)
        and _ART.fullmatch(artifact) is not None
        and isinstance(sha, str)
        and _SHA.fullmatch(sha) is not None
        and type(limit) is int
        and 1 <= limit <= MAX_PUSH_BYTES
        and (
            action == "plan"
            or (isinstance(request_id, str) and _REQUEST.fullmatch(request_id) is not None)
        )
        and (action != "cancel" or (isinstance(job_id, str) and _JOB.fullmatch(job_id) is not None))
    )


def fixture_signature(
    secret: bytes,
    owner: str,
    avd_handle: str,
    lifecycle_job_id: str,
    package_id: str,
    destination_path: str,
    artifact_handle: str,
    digest: str,
    mime_type: str,
) -> str:
    """Test-only HMAC; never evidence of Android APK signature or real consent."""
    fields: dict[str, Any] = {
        "protocol": "h4e-synthetic-atomic-file-import-v1",
        "owner": owner,
        "avd_handle": avd_handle,
        "lifecycle_job_id": lifecycle_job_id,
        "package_id": package_id,
        "destination_path": destination_path,
        "artifact_handle": artifact_handle,
        "artifact_sha256": digest,
        "mime_type": mime_type,
    }
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def valid_fixture_key(key: object) -> bool:
    return type(key) is bytes and len(key) == 32


def valid_signature(signature: object, trusted: str) -> bool:
    return (
        isinstance(signature, str)
        and len(signature) == 64
        and hmac.compare_digest(signature, trusted)
    )


def plan_digest(
    info: dict[str, Any],
    lifecycle_id: str,
    destination: str,
    artifact_handle: str,
    artifact_sha256: str,
    mime: str,
    request_id: str,
    max_bytes: int,
) -> str:
    data = {
        "protocol": "h4e-synthetic-file-import-v1",
        "handle": info["handle"],
        "lifecycle": lifecycle_id,
        "destination_sha256": hashlib.sha256(destination.encode("ascii")).hexdigest(),
        "artifact_handle": artifact_handle,
        "artifact_sha256": artifact_sha256,
        "mime": mime,
        "request": request_id,
        "max_bytes": max_bytes,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def request_slot(lifecycle_id: str, destination: str) -> str:
    digest = hashlib.sha256((lifecycle_id + "\x00" + destination).encode("ascii")).hexdigest()
    return "h4e-import-" + digest[:32]

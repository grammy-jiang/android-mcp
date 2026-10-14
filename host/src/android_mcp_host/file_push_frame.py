"""Typed synthetic file writer receipt and exact-target no-overwrite validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PushFrame:
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    package_id: str
    destination_path: str
    artifact_sha256: str
    bytes_written: int
    complete: bool
    atomic: bool
    overwrote: bool
    symlink: bool
    synthetic: bool


def check_push_frame(
    frame: object,
    info: dict[str, Any],
    lifecycle_id: str,
    package: str,
    destination: str,
    artifact_sha256: str,
    size: int,
) -> str | None:
    """Synthetic receipts are never proof of real device-side atomicity."""
    if (
        type(frame) is not PushFrame
        or frame.avd_name != info["name"]
        or frame.avd_handle != info["handle"]
        or frame.lifecycle_job_id != lifecycle_id
        or frame.package_id != package
        or frame.destination_path != destination
        or frame.artifact_sha256 != artifact_sha256
        or type(frame.bytes_written) is not int
        or type(frame.complete) is not bool
        or type(frame.atomic) is not bool
        or type(frame.overwrote) is not bool
        or type(frame.symlink) is not bool
        or frame.synthetic is not True
    ):
        return "BAD_FRAME"
    if frame.overwrote or frame.symlink:
        return "OVERWRITE_DENIED"
    if not frame.complete or not frame.atomic:
        return "PARTIAL_WRITE"
    if frame.bytes_written != size:
        return "CHECKSUM_MISMATCH"
    return None

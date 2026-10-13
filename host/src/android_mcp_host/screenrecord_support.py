"""Strict bounds for private synthetic MP4-shaped screenrecord fixtures.

This verifies a small MP4 box envelope, not video decodability. No real
Android media is gathered or decoded. Never use this as codec attestation.
"""

from __future__ import annotations

import struct
from typing import Any

MAX_VIDEO_BYTES = 1024 * 1024
DEFAULT_VIDEO_BYTES = 262144
DEFAULT_DURATION = 5
MAX_DURATION = 30
SUPPORTED_CODEC = "h264"
SUPPORTED_DISPLAY = 0
_ALLOWED_BRANDS = frozenset({b"isom", b"mp42"})
_BOXES = (b"ftyp", b"moov", b"mdat")


class InvalidSyntheticVideo(ValueError):
    """Untrusted bounded fake media payload."""


def validate_video(payload: Any, *, maximum: int = MAX_VIDEO_BYTES) -> None:
    """Check finite exact three-box synthetic MP4 envelope and reject smuggling."""
    if (
        type(payload) is not bytes
        or type(maximum) is not int
        or not 1 <= maximum <= MAX_VIDEO_BYTES
        or not 44 <= len(payload) <= maximum
    ):
        raise InvalidSyntheticVideo("Invalid synthetic video size")
    pos = 0
    chunks: list[bytes] = []
    for expected in _BOXES:
        if pos + 8 > len(payload):
            raise InvalidSyntheticVideo("Truncated MP4 box")
        length = struct.unpack_from(">I", payload, pos)[0]
        kind = payload[pos + 4 : pos + 8]
        if kind != expected or length < 8 or pos + length > len(payload):
            raise InvalidSyntheticVideo("Invalid ordered MP4 boxes")
        data = payload[pos + 8 : pos + length]
        if not data:
            raise InvalidSyntheticVideo("Empty MP4 content box")
        chunks.append(data)
        pos += length
    if pos != len(payload):
        raise InvalidSyntheticVideo("Unexpected MP4 trailer")
    brand = chunks[0]
    if len(brand) < 12 or len(brand) % 4 != 0 or brand[:4] not in _ALLOWED_BRANDS:
        raise InvalidSyntheticVideo("Unsupported synthetic MP4 brand")
    if len(chunks[1]) < 8 or len(chunks[2]) < 8:
        raise InvalidSyntheticVideo("Truncated fake MP4 metadata or payload")


def valid_record_request(
    duration_s: object, display_id: object, codec: object, max_bytes: object
) -> bool:
    return (
        type(duration_s) is int
        and 1 <= duration_s <= MAX_DURATION
        and type(display_id) is int
        and display_id == SUPPORTED_DISPLAY
        and type(codec) is str
        and codec == SUPPORTED_CODEC
        and type(max_bytes) is int
        and 64 <= max_bytes <= MAX_VIDEO_BYTES
    )

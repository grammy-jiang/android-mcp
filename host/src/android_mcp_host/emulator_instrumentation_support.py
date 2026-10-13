"""Bounded, structured reports for synthetic-only Host instrumentation fixtures."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

_COMPONENT = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
    r"/[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z",
    re.ASCII,
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MAX_COMPONENT_LENGTH = 255
MAX_OUTPUT_BYTES = 8192
MAX_TEST_CASES = 256


def valid_component(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_COMPONENT_LENGTH
        and _COMPONENT.fullmatch(value) is not None
    )


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def parse_fixture_result(value: object) -> dict[str, int] | None:
    """Only count synthetic fixture cases; never surface raw stdout or log data."""
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return None
    try:
        result: Any = json.loads(value)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(result, dict) or set(result) != {
        "passed",
        "failed",
        "total",
        "synthetic",
    }:
        return None
    if result["synthetic"] is not True:
        return None
    passed, failed, total = result["passed"], result["failed"], result["total"]
    if any(type(amount) is not int for amount in (passed, failed, total)):
        return None
    if not 1 <= total <= MAX_TEST_CASES or not 0 <= passed <= total:
        return None
    if not 0 <= failed <= total or passed + failed != total:
        return None
    return {"passed": passed, "failed": failed, "total": total}


def claim_fixture_lock(root: Path, avd_handle: str) -> int | None:
    """Nonblocking owner-scoped lock prevents racing runs on one fake AVD."""
    digest = hashlib.sha256(avd_handle.encode("ascii")).hexdigest()[:32]
    filename = root / ("fixture-instrumentation-" + digest + ".lock")
    fd = os.open(
        filename,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError("Unsafe fixture lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd
    except BaseException:
        os.close(fd)
        raise

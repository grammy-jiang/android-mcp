"""Typed, finite, fake-only Android UI input intentions and command previews.

No generic adb shell, input text, user-supplied executable or transport ID.
The first token is an inert test fixture protocol, not a real binary.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_XY = 4095
MAX_DURATION_MS = 2000
MAX_GENERATION = 2**31 - 1
ALLOWED_KEYS = frozenset(
    {
        "KEYCODE_BACK",
        "KEYCODE_DPAD_UP",
        "KEYCODE_DPAD_DOWN",
        "KEYCODE_DPAD_LEFT",
        "KEYCODE_DPAD_RIGHT",
    }
)
_WINDOW = re.compile(r"win_[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_NODE = re.compile(r"node_[A-Za-z0-9_-]{1,40}\Z", re.ASCII)
_JOB = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)


def valid_ui_target(
    window_id: object, generation: object, rotation: object, focused_node_id: object
) -> bool:
    return (
        isinstance(window_id, str)
        and _WINDOW.fullmatch(window_id) is not None
        and type(generation) is int
        and 1 <= generation <= MAX_GENERATION
        and type(rotation) is int
        and rotation in (0, 1, 2, 3)
        and isinstance(focused_node_id, str)
        and _NODE.fullmatch(focused_node_id) is not None
    )


def valid_lifecycle_job(value: object) -> bool:
    return isinstance(value, str) and _JOB.fullmatch(value) is not None


def valid_request_id(value: object) -> bool:
    return isinstance(value, str) and _REQUEST.fullmatch(value) is not None


def valid_action_intent(
    kind: object,
    *,
    x: object = None,
    y: object = None,
    x2: object = None,
    y2: object = None,
    duration_ms: object = None,
    keycode: object = None,
) -> bool:
    def coord(value: object) -> bool:
        return type(value) is int and 0 <= value <= MAX_XY

    if kind == "tap":
        return (
            coord(x)
            and coord(y)
            and x2 is None
            and y2 is None
            and duration_ms is None
            and keycode is None
        )
    if kind == "swipe":
        return (
            coord(x)
            and coord(y)
            and coord(x2)
            and coord(y2)
            and type(duration_ms) is int
            and 100 <= duration_ms <= MAX_DURATION_MS
            and keycode is None
        )
    if kind == "key":
        return (
            x is None
            and y is None
            and x2 is None
            and y2 is None
            and duration_ms is None
            and isinstance(keycode, str)
            and keycode in ALLOWED_KEYS
        )
    return False


def intent_digest(**kwargs: Any) -> str:
    fields = {key: val for key, val in kwargs.items() if val is not None}
    data = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def compile_safe_argv(
    avd_name: str,
    kind: str,
    *,
    x: int | None = None,
    y: int | None = None,
    x2: int | None = None,
    y2: int | None = None,
    duration_ms: int | None = None,
    keycode: str | None = None,
) -> list[str]:
    """Return an inert synthetic fixture protocol with only fixed argv fields."""
    if not valid_action_intent(
        kind,
        x=x,
        y=y,
        x2=x2,
        y2=y2,
        duration_ms=duration_ms,
        keycode=keycode,
    ):
        raise ValueError("Invalid bounded synthetic UI intent")
    argv = ["fixture-ui-input", "--avd", avd_name, kind]
    if kind == "tap":
        assert x is not None and y is not None
        argv.extend((str(x), str(y)))
    elif kind == "swipe":
        assert None not in (x, y, x2, y2, duration_ms)
        argv.extend(str(value) for value in (x, y, x2, y2, duration_ms))
    else:
        assert keycode is not None
        argv.append(keycode)
    return argv


def coordinates_fit(
    kind: str,
    width: object,
    height: object,
    x: object,
    y: object,
    x2: object,
    y2: object,
) -> bool:
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= MAX_XY + 1
        or not 1 <= height <= MAX_XY + 1
    ):
        return False
    if kind == "key":
        return True
    if type(x) is not int or type(y) is not int or not 0 <= x < width or not 0 <= y < height:
        return False
    return kind != "swipe" or (
        type(x2) is int and type(y2) is int and 0 <= x2 < width and 0 <= y2 < height
    )


def action_slot(lifecycle_id: str, window_id: str, intent_sha: str) -> str:
    """Exactly one durable slot per action intent in one synthetic window."""
    value = hashlib.sha256(
        (lifecycle_id + "\x00" + window_id + "\x00" + intent_sha).encode("ascii")
    ).hexdigest()
    return "h4f-ui-" + value[:32]


def action_plan_digest(
    avd_handle: str,
    lifecycle_id: str,
    window_id: str,
    generation: int,
    rotation: int,
    focus: str,
    intent_sha: str,
    request_id: str,
) -> str:
    fields = {
        "operation": "h4f-private-synthetic-ui-v1",
        "avd_handle": avd_handle,
        "lifecycle_job_id": lifecycle_id,
        "window_id": window_id,
        "window_generation": generation,
        "rotation": rotation,
        "focused_node_id": focus,
        "intent_sha256": intent_sha,
        "request_id": request_id,
    }
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()

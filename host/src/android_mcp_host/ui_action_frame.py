"""Exact synthetic window and execution-frame validation for H4.f."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from android_mcp_host.ui_action_support import MAX_XY


@dataclass(frozen=True, slots=True)
class UiWitness:
    avd_handle: str
    lifecycle_job_id: str
    window_id: str
    window_generation: int
    rotation: int
    focused_node_id: str
    width: int
    height: int
    secure_window: bool
    locked_window: bool
    synthetic: bool


@dataclass(frozen=True, slots=True)
class UiActionFrame:
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    window_id: str
    window_generation: int
    rotation: int
    focused_node_id: str
    complete: bool
    applied: bool
    synthetic: bool


def witness_error(
    witness: object,
    avd_handle: str,
    lifecycle_id: str,
    window_id: str,
    generation: int,
    rotation: int,
    focus: str,
) -> str | None:
    if (
        type(witness) is not UiWitness
        or witness.avd_handle != avd_handle
        or witness.lifecycle_job_id != lifecycle_id
        or witness.window_id != window_id
        or witness.window_generation != generation
        or witness.rotation != rotation
        or witness.focused_node_id != focus
        or witness.synthetic is not True
        or type(witness.secure_window) is not bool
        or type(witness.locked_window) is not bool
    ):
        return "STALE_WINDOW"
    if witness.secure_window or witness.locked_window:
        return "WINDOW_PROTECTED"
    if (
        type(witness.width) is not int
        or type(witness.height) is not int
        or not 1 <= witness.width <= MAX_XY + 1
        or not 1 <= witness.height <= MAX_XY + 1
    ):
        return "STALE_WINDOW"
    return None


def action_frame_error(
    frame: object,
    info: dict[str, Any],
    lifecycle_id: str,
    window_id: str,
    generation: int,
    rotation: int,
    focus: str,
) -> str | None:
    if (
        type(frame) is not UiActionFrame
        or frame.avd_name != info["name"]
        or frame.avd_handle != info["handle"]
        or frame.lifecycle_job_id != lifecycle_id
        or frame.window_id != window_id
        or frame.window_generation != generation
        or frame.rotation != rotation
        or frame.focused_node_id != focus
        or type(frame.complete) is not bool
        or type(frame.applied) is not bool
        or frame.synthetic is not True
    ):
        return "BAD_FRAME"
    if not frame.complete or not frame.applied:
        return "PARTIAL_ACTION"
    return None

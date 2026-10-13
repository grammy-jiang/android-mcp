"""H4.b owner-pinned, synthetic-only, redacted UI tree inspection.

Production does not inject an inspection backend or user approval and cannot
run uiautomator or issue any ADB/Accessibility action. Only an explicitly
injected synthetic test fixture may supply raw XML internally.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from android_mcp_host.avd_provisioning import AvdProvisioner
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.emulator_debug_support import verified_fake_target
from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock
from android_mcp_host.emulator_lifecycle import EmulatorLifecycle
from android_mcp_host.ui_hierarchy_support import (
    MAX_XML_BYTES,
    InvalidUiTree,
    parse_ui_xml,
)

_LIFECYCLE = re.compile(r"job_[A-Za-z0-9_-]{32}\Z", re.ASCII)
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}\Z", re.ASCII)
_WINDOW = re.compile(r"win_[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_READ_TIMEOUT_S = 3.0
_ERRORS = {
    "INVALID_ACTION": "Unsupported synthetic UI tree operation",
    "INVALID_INPUT": "UI request has invalid target or request fields",
    "NOT_OWNED": "Selected private disposable AVD is not confirmed",
    "CONSENT_REQUIRED": "Valid independent UI inspection approval is absent",
    "EXECUTION_DISABLED": "Real ADB and Accessibility UI reads remain disabled",
    "UNVERIFIED_TARGET": "Exact running synthetic AVD is no longer confirmed",
    "BUSY": "Concurrent private emulator fixture operation is unavailable",
    "CAPABILITY_UNAVAILABLE": "UI hierarchy capability is not enabled in fixture",
    "WINDOW_PROTECTED": "Protected or locked UI window cannot be inspected",
    "MODE_CHANGED": "UI window state changed during inspection",
    "BAD_FRAME": "Synthetic UI response did not match the selected target",
    "INVALID_XML": "Untrusted UI hierarchy failed bounded validation",
    "TIMEOUT": "UI inspection deadline expired without confirmed output",
    "RUNNER_FAILED": "Synthetic UI fixture is unavailable",
}


@dataclass(frozen=True, slots=True)
class UiApproval:
    owner: str
    avd_handle: str
    lifecycle_job_id: str
    purpose: str
    valid_until_epoch: float


@dataclass(frozen=True, slots=True)
class UiTreeFrame:
    xml_bytes: bytes
    avd_name: str
    avd_handle: str
    lifecycle_job_id: str
    window_id: str
    secure_window: bool
    locked_window: bool
    ui_capability_enabled: bool
    synthetic: bool
    mode_before: str
    mode_after: str


FixtureReader = Callable[[str, str, str, float, int], UiTreeFrame]


def get_ui_hierarchy_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-ui-hierarchy.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged UI hierarchy schema")
    return value


def _reply(
    status: str,
    *,
    name: str | None = None,
    handle: str | None = None,
    lifecycle_id: str | None = None,
    window_id: str | None = None,
    parsed: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [] if parsed is None else parsed["nodes"]
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "avd_name": name,
        "avd_handle": handle,
        "lifecycle_job_id": lifecycle_id,
        "window_id": window_id,
        "focused_node_id": None if parsed is None else parsed["focused_node_id"],
        "rotation": None if parsed is None else parsed["rotation"],
        "node_count": len(nodes),
        "nodes": nodes,
        "target": "disposable_emulator_only",
        "sensitivity_class": "redacted_ui",
        "synthetic_fixture_only": True,
        "real_ui_access_enabled": False,
        "accessibility_bypass_enabled": False,
        "physical_device_writes_enabled": False,
        "raw_xml_returned": False,
        "errors": [{"code": error, "message": _ERRORS[error]}] if error else [],
    }


class UiHierarchyService:
    """Exact private disposable AVD; parser never trusts a fixture's identity."""

    def __init__(
        self,
        provisioner: AvdProvisioner,
        lifecycle: EmulatorLifecycle,
        jobs: DurableJobStore,
        *,
        owner: str,
        approval: UiApproval | None = None,
        fixture_reader: FixtureReader | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            not jobs.validate_owner(owner)
            or owner != provisioner.trusted_owner
            or owner != lifecycle._owner
            or lifecycle.provisioner is not provisioner
        ):
            raise ValueError("Untrusted synthetic UI reader ownership")
        self._provisioner = provisioner
        self._lifecycle = lifecycle
        self._jobs = jobs
        self._owner = owner
        self._approval = approval
        self._fixture = fixture_reader
        self._clock = clock

    def _approved(self, avd_handle: str, lifecycle_id: str) -> bool:
        approval = self._approval
        if approval is None:
            return False
        try:
            remaining = approval.valid_until_epoch - self._clock()
        except (ValueError, TypeError, ArithmeticError):
            return False
        return (
            approval.owner == self._owner
            and approval.avd_handle == avd_handle
            and approval.lifecycle_job_id == lifecycle_id
            and approval.purpose == "synthetic-ui-inspection"
            and type(approval.valid_until_epoch) in (float, int)
            and math.isfinite(remaining)
            and 0 < remaining <= 300
        )

    def _inspect(self, info: dict[str, Any], lid: str) -> dict[str, Any]:
        base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lid}
        assert self._fixture is not None
        try:
            frame = self._fixture(info["name"], info["handle"], lid, _READ_TIMEOUT_S, MAX_XML_BYTES)
        except subprocess.TimeoutExpired:
            return _reply("uncertain", error="TIMEOUT", **base)
        except (OSError, RuntimeError, ValueError, TypeError, subprocess.SubprocessError):
            return _reply("unavailable", error="RUNNER_FAILED", **base)
        if not verified_fake_target(self._lifecycle, info, lid):
            return _reply("uncertain", error="UNVERIFIED_TARGET", **base)
        # Sensitive data cannot be released after its out-of-band grant expires.
        if not self._approved(info["handle"], lid):
            return _reply("blocked", error="CONSENT_REQUIRED", **base)
        if (
            type(frame) is not UiTreeFrame
            or frame.avd_name != info["name"]
            or frame.avd_handle != info["handle"]
            or frame.lifecycle_job_id != lid
            or frame.synthetic is not True
            or type(frame.ui_capability_enabled) is not bool
            or type(frame.secure_window) is not bool
            or type(frame.locked_window) is not bool
            or not isinstance(frame.window_id, str)
            or _WINDOW.fullmatch(frame.window_id) is None
        ):
            return _reply("unavailable", error="BAD_FRAME", **base)
        if frame.mode_before != frame.mode_after or frame.mode_after != "normal":
            return _reply("unavailable", error="MODE_CHANGED", **base)
        if frame.secure_window or frame.locked_window:
            return _reply("blocked", error="WINDOW_PROTECTED", **base)
        if not frame.ui_capability_enabled:
            return _reply("blocked", error="CAPABILITY_UNAVAILABLE", **base)
        try:
            parsed = parse_ui_xml(frame.xml_bytes)
        except (InvalidUiTree, ValueError, TypeError):
            return _reply("unavailable", error="INVALID_XML", **base)
        return _reply("ok", window_id=frame.window_id, parsed=parsed, **base)

    def submit(
        self,
        action: str,
        avd_name: str,
        avd_handle: str,
        lifecycle_job_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"plan", "inspect"}:
            return _reply("blocked", error="INVALID_ACTION")
        if (
            not isinstance(lifecycle_job_id, str)
            or _LIFECYCLE.fullmatch(lifecycle_job_id) is None
            or (
                action == "inspect"
                and (not isinstance(request_id, str) or _REQUEST.fullmatch(request_id) is None)
            )
        ):
            return _reply("blocked", error="INVALID_INPUT")
        info = self._provisioner.verify_owned(avd_name, avd_handle)
        if info is None:
            return _reply("blocked", error="NOT_OWNED")
        base = {"name": info["name"], "handle": info["handle"], "lifecycle_id": lifecycle_job_id}
        if action == "plan":
            return _reply("planned", **base)
        if not self._approved(avd_handle, lifecycle_job_id):
            return _reply("blocked", error="CONSENT_REQUIRED", **base)
        if self._fixture is None:
            return _reply("blocked", error="EXECUTION_DISABLED", **base)
        if not verified_fake_target(self._lifecycle, info, lifecycle_job_id):
            return _reply("blocked", error="UNVERIFIED_TARGET", **base)
        try:
            fd = claim_fixture_lock(self._jobs.private_root, info["handle"])
        except OSError:
            return _reply("blocked", error="BUSY", **base)
        if fd is None:
            return _reply("blocked", error="BUSY", **base)
        try:
            return self._inspect(info, lifecycle_job_id)
        finally:
            os.close(fd)

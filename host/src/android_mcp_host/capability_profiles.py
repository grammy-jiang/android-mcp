"""Fail-closed Host capability profiles, ledger and ephemeral target hints.

A capability *description* is never a grant. A target hint can identify a
recent synthetic transport but cannot authorize a device operation or lease.
Only Host configuration can select a profile; the MCP Tool accepts no inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any, Protocol, cast

from android_mcp_host.adb import AdbReport, valid_device_serial

_CANONICAL_RISK_DIGEST = "9e5d6d47452a3969d2d854ea02c990902ddb868c4832e2302f0e064b58afe991"
MAX_ACTIVE_TARGET_HINTS = 128
_RISK_ALLOWED = {
    "safe": frozenset({"D0"}),
    "diagnostic": frozenset({"D0", "D1"}),
}
_PRIORITY = {"D0": 0, "D1": 1, "W2": 2, "W3": 3, "X4": 4, "X5": 5}
_IMPLEMENTED_D0 = frozenset({"A01", "A02", "H01"})
_IMPLEMENTED_D1 = frozenset({"A10", "A12", "A13", "A14", "A21"})
_IMPLEMENTED = _IMPLEMENTED_D0 | _IMPLEMENTED_D1
_DISABLED_PREVIEWS = frozenset({"A22", "A25"})
_DISPOSITIONS = frozenset(
    {
        "implemented_read_only",
        "implemented_disabled",
        "plan_only",
        "excluded_by_security",
    }
)
_EXPECTED_IDS = tuple(
    sorted(
        f"{group}{number:02}"
        for group, end in (("A", 38), ("H", 24), ("P", 6), ("F", 12), ("R", 7), ("E", 8))
        for number in range(1, end + 1)
    )
)
_TOOL_PROVIDERS = frozenset({"adb", "fastboot", "sdk", "java", "gradle"})
_EXTERNAL_PROVIDERS = frozenset({"play", "firebase", "aosp_worker", "git", "ndk", "artifact"})
_REASONS = frozenset(
    {
        "OK",
        "NOT_INSTALLED",
        "NOT_EXECUTABLE",
        "PERMISSION_DENIED",
        "MALFORMED_VERSION",
        "TIMEOUT",
        "OUTPUT_LIMIT",
        "NONZERO_EXIT",
        "EXEC_FAILED",
        "SDK_PLATFORM_NOT_FOUND",
        "PROBE_FAILED",
    }
)


class InventoryProbe(Protocol):
    def inspect(self) -> dict[str, object]: ...


def _resource(filename: str) -> Any:
    return files("android_mcp_host.wire_schemas").joinpath(filename)


def get_capability_output_schema() -> dict[str, Any]:
    """Read the packaged Host-only v1 output Schema."""
    data: Any = json.loads(
        _resource("host-capability-profile.v1.schema.json").read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("Host capability schema must be a JSON object")
    return data


def load_ledger() -> list[dict[str, Any]]:
    """Load and validate the immutable-by-client 95-family Host ledger."""
    data: Any = json.loads(_resource("host-family-ledger.v1.json").read_text(encoding="utf-8"))
    validate_ledger(data)
    return cast(list[dict[str, Any]], data)


def validate_ledger(entries: object) -> None:
    """Reject missing/duplicate/misclassified families and unapproved upgrades."""
    if not isinstance(entries, list) or len(entries) != len(_EXPECTED_IDS):
        raise ValueError("Expected exactly 95 Host capability families")
    if any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Capability ledger entries must be objects")
    ids = [entry.get("catalog_id") for entry in entries]
    if ids != list(_EXPECTED_IDS):
        raise ValueError("Missing, duplicate or unordered Host capability family")
    for entry in entries:
        family = entry["catalog_id"]
        risk = entry.get("risk")
        disposition = entry.get("disposition")
        if (
            risk not in _PRIORITY
            or entry.get("owner") != "host"
            or disposition not in _DISPOSITIONS
            or entry.get("provider") not in (_TOOL_PROVIDERS | _EXTERNAL_PROVIDERS)
        ):
            raise ValueError("Invalid Host capability risk, owner, provider or disposition")
        if risk == "X5" and disposition != "excluded_by_security":
            raise ValueError("Restricted X5 operation cannot become runnable")
        if disposition == "excluded_by_security" and risk != "X5":
            raise ValueError("Incorrectly excluded risk")
        if disposition == "implemented_read_only" and (
            family not in _IMPLEMENTED or _PRIORITY[risk] > 1
        ):
            raise ValueError("Unapproved read-only capability upgrade")
        if family in _IMPLEMENTED and disposition != "implemented_read_only":
            raise ValueError("Verified read-only family lost its baseline designation")
        if disposition == "implemented_disabled" and family not in _DISABLED_PREVIEWS:
            raise ValueError("Unsupported disabled-operation implementation claim")
        if family in _DISABLED_PREVIEWS and disposition != "implemented_disabled":
            raise ValueError("Mutation preview must remain disabled")
        evidence = entry.get("test_ids")
        sha = entry.get("merged_sha")
        if disposition in {"implemented_read_only", "implemented_disabled"}:
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("Implemented family lacks test evidence")
            if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
                raise ValueError("Implemented family lacks an exact merged revision")
        elif entry.get("verification") != "not_run" or sha is not None:
            raise ValueError("Plan-only or excluded family cannot claim implementation")
    digest = hashlib.sha256(
        "|".join(f"{entry['catalog_id']}:{entry['risk']}" for entry in entries).encode()
    ).hexdigest()
    if digest != _CANONICAL_RISK_DIGEST:
        raise ValueError("Unapproved Host capability risk classification change")


class CapabilityProfiles:
    """Host-selected disclosure profile. Availability never implies authority."""

    def __init__(
        self,
        *,
        profile_ids: Sequence[str] = ("safe",),
        toolchain: InventoryProbe | None = None,
        inventory_enabled: bool = False,
        connected_providers: frozenset[str] = frozenset(),
    ) -> None:
        if len(profile_ids) != 1 or profile_ids[0] not in _RISK_ALLOWED:
            raise ValueError("Choose exactly one approved Host capability profile")
        if not isinstance(connected_providers, frozenset) or not (
            connected_providers <= _EXTERNAL_PROVIDERS
        ):
            raise ValueError("Unrecognized Host-side provider")
        if type(inventory_enabled) is not bool:
            raise ValueError("Host inventory Tool registration flag must be boolean")
        self._inventory_enabled = inventory_enabled
        self._profile = profile_ids[0]
        self._toolchain = toolchain
        self._connected = connected_providers
        self._entries = load_ledger()
        self._index = {entry["catalog_id"]: entry for entry in self._entries}

    def _snapshot_tools(self) -> dict[str, Any]:
        if self._toolchain is None:
            return {}
        try:
            report = self._toolchain.inspect()
        except (OSError, RuntimeError, ValueError):
            return {}
        if not isinstance(report, dict) or report.get("runtime") != "host":
            return {}
        tools = report.get("tools")
        return tools if isinstance(tools, dict) else {}

    def _provider_status(self, entry: dict[str, Any], tools: dict[str, Any]) -> str:
        provider = entry["provider"]
        if provider in _TOOL_PROVIDERS:
            item = tools.get(provider)
            if not isinstance(item, dict):
                return "NOT_INSTALLED"
            reason = item.get("reason")
            if item.get("runnable") is not True or reason != "OK":
                return (
                    reason
                    if isinstance(reason, str) and reason in _REASONS and reason != "OK"
                    else "NOT_INSTALLED"
                )
            return "OK"
        if provider in self._connected:
            return "OK"
        return "PROVIDER_NOT_CONNECTED"

    def _capability(self, entry: dict[str, Any], tools: dict[str, Any]) -> dict[str, Any]:
        family = entry["catalog_id"]
        risk = entry["risk"]
        disposition = entry["disposition"]
        reason = "NOT_IMPLEMENTED"
        state = "plan_only"
        authorized = False
        if risk == "X5":
            state, reason = "excluded_by_security", "EXCLUDED_BY_SECURITY"
        elif risk not in _RISK_ALLOWED[self._profile]:
            state, reason = "not_exposed", "PROFILE_DENIED"
        else:
            provider_reason = self._provider_status(entry, tools)
            if provider_reason != "OK":
                state, reason = "unavailable", provider_reason
            elif family == "H01" and not self._inventory_enabled:
                state, reason = "not_exposed", "TOOL_DISABLED"
            elif disposition == "implemented_read_only":
                if family in _IMPLEMENTED_D0:
                    state, reason, authorized = "runnable", "OK", True
                else:
                    state, reason = "requires_target", "EXPLICIT_TARGET_REQUIRED"
            elif disposition == "implemented_disabled":
                state, reason = "implemented_disabled", "MUTATION_DISABLED"
        return {
            "catalog_id": family,
            "risk": risk,
            "state": state,
            "reason": reason,
            "authorized": authorized,
        }

    def capability(self, family_id: str) -> dict[str, Any]:
        """Inspect one known ID, including restricted ones as denied state."""
        if family_id not in self._index:
            raise ValueError("Unknown Host capability ID")
        return self._capability(self._index[family_id], self._snapshot_tools())

    def snapshot(self) -> dict[str, object]:
        """Bounded, redacted public catalog for the chosen safe Host profile."""
        tools = self._snapshot_tools()
        allowed = _RISK_ALLOWED[self._profile]
        return {
            "schema_version": 1,
            "runtime": "host",
            "profile": self._profile,
            "mutation_enabled": False,
            "target_authority": False,
            "capabilities": [
                self._capability(entry, tools)
                for entry in self._entries
                if entry["risk"] in allowed
            ],
        }


class TargetHintRegistry:
    """Ephemeral transport comparison; never a lease, grant or device authority."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_s: float = 30.0) -> None:
        if not 0 < ttl_s <= 60:
            raise ValueError("Target hint TTL must be positive and at most 60 seconds")
        self._clock = clock
        self._ttl_s = ttl_s
        self._hints: dict[str, tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _matches(report: AdbReport, device_id: str, transport_id: str) -> bool:
        if (
            not valid_device_serial(device_id)
            or not isinstance(transport_id, str)
            or re.fullmatch(r"[1-9][0-9]{0,9}", transport_id) is None
            or not report.available
            or report.error is not None
        ):
            return False
        matches = [device for device in report.devices if device.device_id == device_id]
        return (
            len(matches) == 1
            and matches[0].state == "device"
            and matches[0].properties.get("transport_id") == transport_id
        )

    def issue(self, report: AdbReport, *, device_id: str, transport_id: str) -> dict[str, object]:
        if not self._matches(report, device_id, transport_id):
            raise ValueError("Unverified or ambiguous ADB transport")
        with self._lock:
            now = self._clock()
            for token, (_, _, deadline) in tuple(self._hints.items()):
                if deadline <= now:
                    del self._hints[token]
            if len(self._hints) >= MAX_ACTIVE_TARGET_HINTS:
                raise ValueError("Active target hint budget exceeded")
            token = secrets.token_hex(16)
            if token in self._hints:
                raise ValueError("Target reference collision")
            self._hints[token] = (device_id, transport_id, now + self._ttl_s)
        return {
            "target_ref": token,
            "kind": "observation_only",
            "authorization": "none",
        }

    def validate(self, target_ref: str, report: AdbReport) -> bool:
        if not isinstance(target_ref, str):
            return False
        with self._lock:
            item = self._hints.get(target_ref)
            if item is None:
                return False
            device_id, transport_id, expiry = item
            if self._clock() >= expiry or not self._matches(report, device_id, transport_id):
                del self._hints[target_ref]
                return False
            return True

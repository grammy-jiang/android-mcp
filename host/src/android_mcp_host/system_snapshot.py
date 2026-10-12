"""Typed Android diagnostics using only fixed bounded, device-pinned ADB reads.

Distinct opt-in public Tool: the existing nine-group adb_observe v1 contract
and its fixed input/output schemas stay byte-for-byte unchanged.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any

from android_mcp_host.adb import AdbClient
from android_mcp_host.command_runner import OutputLimitExceeded, completed_bounded
from android_mcp_host.device_guard import require_online, valid_device_id

MAX_GROUPS = 5
OUTPUT_BYTES = 65536

# No external caller can provide arbitrary command text, service names or keys.
COMMANDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "identity": (
        ("api_level", ("shell", "getprop", "ro.build.version.sdk")),
        ("model", ("shell", "getprop", "ro.product.model")),
    ),
    "battery": (("battery", ("shell", "dumpsys", "battery")),),
    "storage": (("storage", ("shell", "df", "-k", "/data")),),
    "display": (
        ("size", ("shell", "wm", "size")),
        ("density", ("shell", "wm", "density")),
    ),
    "network": (("network", ("shell", "dumpsys", "connectivity")),),
}
Reader = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().+\-]{0,95}\Z", re.ASCII)
_SIZE = re.compile(r"(?m)^Physical size: ([0-9]{2,5})x([0-9]{2,5})$", re.ASCII)
_DENSITY = re.compile(r"(?m)^Physical density: ([0-9]{2,4})$", re.ASCII)
_NETWORK = re.compile(r"(?m)^Active default network: (null|[0-9]{1,9})$", re.ASCII)


def _run(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return completed_bounded(argv, timeout_s, OUTPUT_BYTES)


def get_snapshot_output_schema() -> dict[str, Any]:
    """Load the packaged, Host-only typed system snapshot v1 JSON schema."""
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-system-snapshot.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged Host system snapshot schema")
    return value


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": "Android system diagnostic was unavailable or incomplete"}


def _number(text: str, low: int, high: int) -> int | None:
    stripped = text.strip()
    if not stripped.isascii() or not stripped.isdecimal() or len(stripped) > 16:
        return None
    number = int(stripped)
    return number if low <= number <= high else None


def _dumpsys_field(text: str, key: str) -> str | None:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}:\s*(\S+)\s*$", re.ASCII)
    matches = pattern.findall(text)
    return matches[0] if len(matches) == 1 else None


def _parse(key: str, raw: str) -> dict[str, Any]:
    """Return only trusted typed fields; missing/invalid values stay absent."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > OUTPUT_BYTES or "\ufffd" in raw:
        return {}
    if key == "api_level":
        value = _number(raw, 1, 100)
        return {"api_level": value} if value is not None else {}
    if key == "model":
        model_text = raw.strip()
        return {"model": model_text} if _MODEL.fullmatch(model_text) is not None else {}
    if key == "battery":
        level_raw = _dumpsys_field(raw, "level")
        scale_raw = _dumpsys_field(raw, "scale")
        level = _number(level_raw or "", 0, 1000)
        scale = _number(scale_raw or "", 1, 1000)
        values: dict[str, Any] = {}
        if level is not None and scale is not None and level <= scale:
            values["battery_percent"] = round(level * 100.0 / scale, 1)
        temperature = _number(_dumpsys_field(raw, "temperature") or "", 0, 900)
        if temperature is not None:
            values["battery_temperature_c"] = temperature / 10.0
        powered = _dumpsys_field(raw, "AC powered")
        if powered in {"true", "false"}:
            values["battery_ac_powered"] = powered == "true"
        return values
    if key == "storage":
        rows = raw.splitlines()
        if len(rows) < 2:
            return {}
        # ADB's fixed `df -k /data` returns a header and one /data row.
        matches = [row.split() for row in rows[1:] if row.split()[-1:] == ["/data"]]
        if len(matches) != 1 or len(matches[0]) < 6:
            return {}
        columns = matches[0]
        total = _number(columns[1], 1, 1_000_000_000_000)
        free = _number(columns[3], 0, 1_000_000_000_000)
        if total is None or free is None or free > total:
            return {}
        return {"total_kib": total, "free_kib": free}
    if key == "size":
        match = _SIZE.search(raw)
        if match is None:
            return {}
        width = _number(match.group(1), 100, 32768)
        height = _number(match.group(2), 100, 32768)
        if width is None or height is None:
            return {}
        return {"width_px": width, "height_px": height}
    if key == "density":
        match = _DENSITY.search(raw)
        if match is None:
            return {}
        density = _number(match.group(1), 72, 1200)
        return {"density_dpi": density} if density is not None else {}
    if key == "network":
        match = _NETWORK.search(raw)
        if match is None:
            return {}
        return {"default_network_connected": match.group(1) != "null"}
    return {}


class SystemSnapshot:
    """No raw shell input, no implicit device, and no unbounded CLI results."""

    def __init__(
        self,
        adb: AdbClient | None = None,
        *,
        reader: Reader = _run,
        timeout_s: float = 5.0,
    ) -> None:
        if not 0 < timeout_s <= 10:
            raise ValueError("Probe deadline must be positive and at most 10 seconds")
        self._adb = adb if adb is not None else AdbClient()
        self._reader = reader
        self._timeout = timeout_s

    def inspect(self, device_id: str, groups: Sequence[str]) -> dict[str, Any]:
        valid_id = valid_device_id(device_id)
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id if valid_id else "",
            "status": "error",
            "results": [],
            "errors": [],
        }

        def fail(code: str) -> dict[str, Any]:
            response["errors"].append(_error(code))
            response["status"] = "partial" if response["results"] else "error"
            return response

        if not valid_id:
            return fail("INVALID_DEVICE_ID")
        if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence):
            return fail("INVALID_GROUPS")
        if not 1 <= len(groups) <= MAX_GROUPS:
            return fail("INVALID_GROUPS")
        if any(not isinstance(group, str) or group not in COMMANDS for group in groups):
            return fail("UNKNOWN_GROUP")
        if len(set(groups)) != len(groups):
            return fail("DUPLICATE_GROUPS")
        report = self._adb.inspect()
        problem = require_online(report, device_id)
        if problem is not None:
            return fail(problem["code"])
        executable = report.executable
        if not executable:
            return fail("ADB_NOT_FOUND")

        had_missing = False
        for group in groups:
            values: dict[str, Any] = {}
            for key, suffix in COMMANDS[group]:
                try:
                    result = self._reader([executable, "-s", device_id, *suffix], self._timeout)
                except OutputLimitExceeded:
                    return fail("OUTPUT_LIMIT")
                except subprocess.TimeoutExpired:
                    return fail("PROBE_TIMEOUT")
                except (OSError, RuntimeError, ValueError):
                    return fail("PROBE_EXEC_FAILED")
                if (
                    len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
                    > OUTPUT_BYTES
                ):
                    return fail("OUTPUT_LIMIT")
                if result.returncode != 0:
                    return fail("PROBE_FAILED")
                if result.stderr:
                    had_missing = True
                parsed = _parse(key, result.stdout)
                if not parsed:
                    had_missing = True
                values.update(parsed)
            response["results"].append({"group": group, "values": values})
        if had_missing:
            response["errors"].append(_error("PARTIAL_DATA"))
        response["status"] = "partial" if had_missing else "ok"
        return response

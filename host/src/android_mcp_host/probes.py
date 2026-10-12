"""Typed, bounded ADB observation commands for a *specific* connected device.

There is deliberately no model-supplied shell, package, property key, command
argument, or executable path. All remote commands come from this fixed table.
The tool refuses ambiguous/unauthorized/offline targets before running probes.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

from android_mcp_host.adb import AdbClient
from android_mcp_host.device_guard import require_online, valid_device_id

# Names used in the MCP argument schema and the local policy registry.
ProbeName: TypeAlias = str


@dataclass(frozen=True, slots=True)
class CommandSpec:
    key: str
    argv: tuple[str, ...]
    max_chars: int = 2048


# These commands require ADB's normal shell identity; never invoke su/root.
# No user-provided text can appear after `shell` or as a property key.
PROBES: Mapping[str, tuple[CommandSpec, ...]] = {
    "identity": (
        CommandSpec("manufacturer", ("shell", "getprop", "ro.product.manufacturer")),
        CommandSpec("model", ("shell", "getprop", "ro.product.model")),
        CommandSpec("android_release", ("shell", "getprop", "ro.build.version.release")),
        CommandSpec("api_level", ("shell", "getprop", "ro.build.version.sdk")),
        CommandSpec("build_type", ("shell", "getprop", "ro.build.type")),
        CommandSpec("lineage_version", ("shell", "getprop", "ro.lineage.version")),
    ),
    "boot": (
        CommandSpec("boot_completed", ("shell", "getprop", "sys.boot_completed")),
        CommandSpec("debuggable", ("shell", "getprop", "ro.debuggable")),
        CommandSpec("verified_boot_state", ("shell", "getprop", "ro.boot.verifiedbootstate")),
    ),
    "battery": (CommandSpec("battery", ("shell", "dumpsys", "battery"), max_chars=4096),),
    "display": (
        CommandSpec("size", ("shell", "wm", "size")),
        CommandSpec("density", ("shell", "wm", "density")),
    ),
    "storage": (CommandSpec("data_free", ("shell", "df", "-k", "/data")),),
    "selinux": (CommandSpec("enforcement", ("shell", "getenforce")),),
    "shell_identity": (CommandSpec("identity", ("shell", "id")),),
    "third_party_packages": (
        CommandSpec("packages", ("shell", "pm", "list", "packages", "-3"), max_chars=12000),
    ),
}

MAX_PROBES = 8
MAX_TOTAL_CHARS = 25000
_MAX_TIMEOUT_S = 10.0


class Reader(Protocol):
    def __call__(
        self, argv: Sequence[str], timeout_s: float
    ) -> subprocess.CompletedProcess[str]: ...


def _run(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    """Executable arguments, never a constructed host shell command."""
    return subprocess.run(
        list(argv),
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout_s,
    )


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    # Device output is untrusted; strip ASCII control bytes other than whitespace
    # so it cannot inject terminal escapes into logs or rendered MCP responses.
    value = "".join(ch for ch in text if ch in "\t\r\n" or ord(ch) >= 32 and ord(ch) != 127)
    value = value.rstrip("\r\n")
    return value[:limit], len(value) > limit


def _safe_stderr(stderr: str) -> str:
    # Remote command stderr is untrusted data. Do not echo arbitrary details
    # to the MCP client; failures are classified by typed error codes.
    return "ADB command failed" if stderr else "ADB command returned nonzero status"


class ProbeService:
    """Read-only observation facade with injectable discovery and subprocesses."""

    def __init__(
        self,
        adb: AdbClient | None = None,
        *,
        adb_executable: str | None = None,
        locate: Callable[[str], str | None] = shutil.which,
        reader: Reader = _run,
        timeout_s: float = 5.0,
    ) -> None:
        if not 0 < timeout_s <= _MAX_TIMEOUT_S:
            raise ValueError("timeout_s must be greater than zero and no more than 10 seconds")
        self._adb = adb if adb is not None else AdbClient()
        self._adb_executable = adb_executable
        self._locate = locate
        self._reader = reader
        self._timeout_s = timeout_s

    def observe(self, device_id: str, probes: Sequence[str]) -> dict[str, Any]:
        """Observe explicit, typed aspects of one device; stop on first error.

        Arguments and membership are validated *before* making any host or
        device call. Never choose the first connected device implicitly.
        """
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id if isinstance(device_id, str) else "",
            "status": "error",
            "results": [],
            "errors": [],
        }
        if not isinstance(device_id, str) or not valid_device_id(device_id):
            response["errors"].append(_error("INVALID_DEVICE_ID", "Invalid device identifier"))
            return response
        if isinstance(probes, (str, bytes)) or not isinstance(probes, Sequence):
            response["errors"].append(_error("INVALID_PROBES", "Expected a list of probe names"))
            return response
        if not probes or len(probes) > MAX_PROBES:
            response["errors"].append(_error("INVALID_PROBES", "Select 1 to 8 probe names"))
            return response
        if any(not isinstance(probe, str) or probe not in PROBES for probe in probes):
            response["errors"].append(_error("INVALID_PROBE", "Unknown probe name"))
            return response
        if len(set(probes)) != len(probes):
            response["errors"].append(_error("INVALID_PROBES", "Duplicate probes are not allowed"))
            return response

        report = self._adb.inspect()
        error = require_online(report, device_id)
        if error:
            response["errors"].append(error)
            return response
        binary = self._adb_executable or self._locate("adb")
        if not binary:
            response["errors"].append(_error("ADB_NOT_FOUND", "ADB executable unavailable"))
            return response

        total_chars = 0
        results: list[dict[str, Any]] = response["results"]
        for name in probes:
            fields: dict[str, str] = {}
            truncated_fields: list[str] = []
            for command in PROBES[name]:
                # Fixed remote arguments: only the discovered device serial varies.
                argv = [binary, "-s", device_id, *command.argv]
                try:
                    result = self._reader(argv, self._timeout_s)
                except subprocess.TimeoutExpired:
                    response["errors"].append(
                        _error("PROBE_TIMEOUT", "ADB observation exceeded its timeout")
                    )
                    response["status"] = "partial" if results else "error"
                    return response
                except OSError:
                    response["errors"].append(
                        _error("PROBE_EXEC_FAILED", "Failed to execute ADB observation")
                    )
                    response["status"] = "partial" if results else "error"
                    return response
                if result.returncode != 0:
                    response["errors"].append(_error("PROBE_FAILED", _safe_stderr(result.stderr)))
                    response["status"] = "partial" if results else "error"
                    return response
                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining <= 0:
                    response["errors"].append(
                        _error("OUTPUT_LIMIT", "Observation output limit reached")
                    )
                    response["status"] = "partial" if results else "error"
                    return response
                text, shortened = _bounded(result.stdout, min(command.max_chars, remaining))
                fields[command.key] = text
                total_chars += len(text)
                if shortened:
                    truncated_fields.append(command.key)
            results.append({"probe": name, "fields": fields, "truncated_fields": truncated_fields})
        response["status"] = "ok"
        return response

"""Exact-package Android diagnostics with bounded parsing and no raw device output.

This service has no APK install/uninstall, pm write, arbitrary shell, or
model-controlled executable. Legacy adb_develop package_details is unchanged.
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

OUTPUT_BYTES = 65536
MAX_PERMISSIONS = 32
_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z", re.ASCII)
_PERMISSION = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,8}\Z", re.ASCII)
_VERSION_NAME = re.compile(r"(?m)^\s*versionName=([A-Za-z0-9][A-Za-z0-9_.+\-]{0,63})\s*$", re.ASCII)
_VERSION_CODE = re.compile(r"(?m)^\s*versionCode=([0-9]{1,12})(?:\s|$)", re.ASCII)
_TARGET_SDK = re.compile(r"(?:^|\s)targetSdk=([0-9]{1,3})(?:\s|$)", re.ASCII)
_MISSING = ("Unable to find package", "Package not found", "Unknown package")
Reader = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def get_package_output_schema() -> dict[str, Any]:
    """A fresh Host-only v1 Tool output schema from wheel resources."""
    data: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-package-diagnostics.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("Invalid packaged Host package diagnostics schema")
    return data


def valid_package(value: object) -> bool:
    """Never allow flags, Unicode confusables, unbounded paths or shell syntax."""
    return (
        isinstance(value, str) and 3 <= len(value) <= 180 and _PACKAGE.fullmatch(value) is not None
    )


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": "Exact package diagnostics could not be fully confirmed"}


def _read(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return completed_bounded(argv, timeout_s, OUTPUT_BYTES)


def _single_number(pattern: re.Pattern[str], data: str, low: int, high: int) -> int | None:
    matches = pattern.findall(data)
    if len(matches) != 1:
        return None
    value = int(matches[0])
    return value if low <= value <= high else None


def _selected_section(data: str, package: str) -> str | None:
    """Only inspect the exact Package [NAME] block, never a prefix match."""
    header = re.compile(
        rf"(?m)^\s{{2,8}}Package \[{re.escape(package)}\](?:\s*\([^\n)]*\))?:\s*$",
        re.ASCII,
    )
    matches = list(header.finditer(data))
    if len(matches) != 1:
        return None
    remainder = data[matches[0].end() :]
    next_package = re.search(r"(?m)^\s{2,8}Package \[", remainder, re.ASCII)
    return remainder[: next_package.start()] if next_package else remainder


def _permissions(section: str, limit: int) -> tuple[list[str], list[str], bool]:
    """Allowlisted names only; never carry through arbitrary dumpsys lines."""
    requested: list[str] = []
    granted: list[str] = []
    active: str | None = None
    clipped = False
    for line in section.splitlines():
        stripped = line.strip()
        if stripped in {"requested permissions:", "install permissions:"}:
            active = "requested" if stripped.startswith("requested") else "install"
            continue
        if not stripped or (
            stripped.endswith(":") and not stripped.startswith("android.permission")
        ):
            active = None
            continue
        if active == "requested":
            if _PERMISSION.fullmatch(stripped) and stripped not in requested:
                if len(requested) == limit:
                    clipped = True
                else:
                    requested.append(stripped)
        elif active == "install":
            permission, marker, remainder = stripped.partition(":")
            if (
                marker
                and _PERMISSION.fullmatch(permission)
                and remainder.strip() == "granted=true"
                and permission not in granted
            ):
                if len(granted) == limit:
                    clipped = True
                else:
                    granted.append(permission)
    return requested, granted, clipped


def _parse(data: str, package: str, include_permissions: bool, limit: int) -> dict[str, Any] | None:
    if not isinstance(data, str) or len(data.encode("utf-8")) > OUTPUT_BYTES or "\ufffd" in data:
        return None
    section = _selected_section(data, package)
    if section is None:
        return None
    names = _VERSION_NAME.findall(section)
    version_name = names[0] if len(names) == 1 else None
    version_code = _single_number(_VERSION_CODE, section, 0, 999_999_999_999)
    target_sdk = _single_number(_TARGET_SDK, section, 1, 100)
    if include_permissions:
        requested, granted, truncated = _permissions(section, limit)
    else:
        requested, granted, truncated = [], [], False
    return {
        "version_name": version_name,
        "version_code": version_code,
        "target_sdk": target_sdk,
        "requested_permissions": requested,
        "granted_permissions": granted,
        "permissions_truncated": truncated,
    }


class PackageInspector:
    """Finite, read-only single-package diagnostics for one online device."""

    def __init__(
        self,
        adb: AdbClient | None = None,
        *,
        reader: Reader = _read,
        timeout_s: float = 5.0,
    ) -> None:
        if not 0 < timeout_s <= 10:
            raise ValueError("Package diagnostic deadline must be within 0-10 seconds")
        self._adb = adb if adb is not None else AdbClient()
        self._reader = reader
        self._timeout = timeout_s

    def inspect(
        self,
        device_id: str,
        package: str,
        *,
        include_permissions: bool = True,
        permission_limit: int = MAX_PERMISSIONS,
    ) -> dict[str, Any]:
        good_serial = valid_device_id(device_id)
        good_package = valid_package(package)
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id if good_serial else "",
            "package": package if good_package else "",
            "status": "error",
            "found": False,
            "version_name": None,
            "version_code": None,
            "target_sdk": None,
            "requested_permissions": [],
            "granted_permissions": [],
            "permissions_truncated": False,
            "errors": [],
        }

        def fail(code: str, status: str = "error") -> dict[str, Any]:
            response["status"] = status
            response["errors"].append(_error(code))
            return response

        if not good_serial:
            return fail("INVALID_DEVICE_ID")
        if not good_package:
            return fail("INVALID_PACKAGE")
        if type(include_permissions) is not bool or type(permission_limit) is not int:
            return fail("INVALID_OPTIONS")
        if not 1 <= permission_limit <= MAX_PERMISSIONS:
            return fail("INVALID_OPTIONS")
        report = self._adb.inspect()
        problem = require_online(report, device_id)
        if problem is not None:
            return fail(problem["code"])
        if not report.executable:
            return fail("ADB_NOT_FOUND")
        argv = [report.executable, "-s", device_id, "shell", "dumpsys", "package", package]
        try:
            result = self._reader(argv, self._timeout)
        except subprocess.TimeoutExpired:
            return fail("PROBE_TIMEOUT")
        except OutputLimitExceeded:
            return fail("OUTPUT_LIMIT")
        except PermissionError:
            return fail("PERMISSION_DENIED")
        except (OSError, RuntimeError, ValueError):
            return fail("PROBE_EXEC_FAILED")
        if len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) > OUTPUT_BYTES:
            return fail("OUTPUT_LIMIT")
        if result.returncode != 0:
            if any(marker in result.stdout or marker in result.stderr for marker in _MISSING):
                return fail("PACKAGE_NOT_FOUND")
            return fail("PROBE_FAILED")
        parsed = _parse(result.stdout, package, include_permissions, permission_limit)
        if parsed is None:
            return fail(
                "PACKAGE_NOT_FOUND"
                if any(m in result.stdout for m in _MISSING)
                else "PACKAGE_VISIBILITY_UNKNOWN",
                "unavailable",
            )
        response["found"] = True
        response.update(parsed)
        if (
            parsed["version_name"] is None
            or parsed["version_code"] is None
            or parsed["target_sdk"] is None
            or parsed["permissions_truncated"]
            or bool(result.stderr)
        ):
            return fail("PARTIAL_DATA", "partial")
        response["status"] = "ok"
        return response

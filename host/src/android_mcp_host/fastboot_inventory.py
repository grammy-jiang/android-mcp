"""Fixed-argv, read-only Fastboot transport inventory with no ADB fallback.

A Fastboot row is an unverified bootloader-mode transport, not proof of
device model, partition state, bootloader unlock state, or Host/Native pairing.
"""

from __future__ import annotations

import json
import os
import platform
import re
import stat
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.adb import valid_device_serial
from android_mcp_host.command_runner import OutputLimitExceeded, completed_bounded
from android_mcp_host.toolchain_inventory import _candidate_paths

OUTPUT_BYTES = 65536
MAX_DEVICES = 32
_VERSION = re.compile(r"(?m)^fastboot version ([0-9][A-Za-z0-9.+_~\-]{0,63})$", re.ASCII)
_USB = re.compile(r"usb:[A-Za-z0-9_.:\-]{1,48}\Z", re.ASCII)
Reader = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def get_fastboot_output_schema() -> dict[str, Any]:
    """Load Host-only v1 inventory schema from packaged resources."""
    data: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-fastboot-inventory.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("Invalid packaged Fastboot inventory schema")
    return data


def _run(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return completed_bounded(argv, timeout_s, OUTPUT_BYTES)


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": "Read-only Fastboot discovery could not be fully confirmed"}


def _parse_devices(stdout: str) -> tuple[list[dict[str, Any]], list[str]]:
    devices: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.split()
        if len(parts) not in (2, 3) or not valid_device_serial(parts[0]):
            errors.append("MALFORMED_FASTBOOT_ROW")
            continue
        serial, state = parts[0], parts[1]
        if state != "fastboot":
            errors.append("INVALID_FASTBOOT_MODE")
            continue
        if serial in seen:
            return [], ["AMBIGUOUS_FASTBOOT_SERIAL"]
        seen.add(serial)
        if len(devices) >= MAX_DEVICES:
            return [], ["DEVICE_LIMIT"]
        transport = "unknown"
        if len(parts) == 3:
            if _USB.fullmatch(parts[2]) is None:
                errors.append("MALFORMED_FASTBOOT_ROW")
                continue
            transport = "usb"
        devices.append(
            {
                "device_id": serial,
                "state": "fastboot",
                "transport": transport,
                "mode": "unverified",
                "device_authorized": False,
            }
        )
    return devices, errors


class FastbootInventory:
    """Read only Fastboot version and devices list; never execute other verbs."""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        sdk_root: Path | None = None,
        reader: Reader = _run,
        timeout_s: float = 5.0,
    ) -> None:
        if not 0 < timeout_s <= 10:
            raise ValueError("Fastboot deadline must be positive and at most 10 seconds")
        if executable is not None and not executable.is_absolute():
            raise ValueError("Trusted Fastboot path must be absolute")
        if sdk_root is not None and not sdk_root.is_absolute():
            raise ValueError("SDK root must be absolute")
        self._path = executable
        self._sdk = sdk_root or (
            Path.home() / "Library/Android/sdk"
            if platform.system() == "Darwin"
            else Path.home() / "Android/Sdk"
        )
        self._reader = reader
        self._timeout = timeout_s

    def _locate(self) -> Path | None:
        if self._path is not None:
            return self._path
        for candidate in _candidate_paths("fastboot", self._sdk):
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def discover(self) -> dict[str, Any]:
        reply: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "status": "unavailable",
            "fastboot": {"available": False, "version": None},
            "devices": [],
            "errors": [],
        }

        def fail(code: str, status: str = "unavailable") -> dict[str, Any]:
            reply["status"] = status
            reply["errors"].append(_error(code))
            return reply

        binary = self._locate()
        if binary is None:
            return fail("FASTBOOT_NOT_FOUND")
        try:
            mode = binary.stat().st_mode
        except FileNotFoundError:
            return fail("FASTBOOT_NOT_FOUND")
        except PermissionError:
            return fail("FASTBOOT_PERMISSION_DENIED")
        except OSError:
            return fail("FASTBOOT_EXEC_FAILED")
        if not stat.S_ISREG(mode) or not mode & 0o111:
            return fail("FASTBOOT_NOT_EXECUTABLE")
        if not os.access(binary, os.X_OK):
            return fail("FASTBOOT_PERMISSION_DENIED")

        def probe(arguments: list[str]) -> subprocess.CompletedProcess[str] | str:
            try:
                result = self._reader([str(binary), *arguments], self._timeout)
            except subprocess.TimeoutExpired:
                return "FASTBOOT_TIMEOUT"
            except OutputLimitExceeded:
                return "OUTPUT_LIMIT"
            except PermissionError:
                return "FASTBOOT_PERMISSION_DENIED"
            except (OSError, ValueError, RuntimeError):
                return "FASTBOOT_EXEC_FAILED"
            if (
                not isinstance(result.stdout, str)
                or not isinstance(result.stderr, str)
                or len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
                > OUTPUT_BYTES
            ):
                return "OUTPUT_LIMIT"
            return result

        version = probe(["--version"])
        if isinstance(version, str):
            return fail(version)
        if version.returncode != 0:
            return fail("FASTBOOT_VERSION_FAILED")
        if version.stderr and "fastboot version " not in version.stderr:
            return fail("FASTBOOT_VERSION_UNVERIFIED")
        match = _VERSION.search(version.stdout + "\n" + version.stderr)
        if match is None:
            return fail("FASTBOOT_VERSION_UNVERIFIED")
        reply["fastboot"] = {"available": True, "version": match.group(1)}

        listing = probe(["devices", "-l"])
        if isinstance(listing, str):
            return fail(listing, "partial")
        if listing.returncode != 0:
            return fail("FASTBOOT_LIST_FAILED", "partial")
        parsed, errors = _parse_devices(listing.stdout)
        if listing.stderr:
            errors.append("FASTBOOT_STDERR_UNVERIFIED")
        reply["devices"] = parsed
        reply["errors"] = [_error(code) for code in errors[:4]]
        reply["status"] = (
            "error"
            if "AMBIGUOUS_FASTBOOT_SERIAL" in errors or "DEVICE_LIMIT" in errors
            else "partial"
            if errors
            else "ok"
        )
        return reply

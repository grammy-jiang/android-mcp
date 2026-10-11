"""Read-only, shell-free Android Platform Tools discovery.

The ADB CLI is a shared host-level resource; calling 'devices' may start its
background daemon. Future mutations will require explicit device selection.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass

ALLOWED_STATES = {
    "device",
    "offline",
    "unauthorized",
    "authorizing",
    "recovery",
    "sideload",
    "bootloader",
    "rescue",
    "no_permissions",
}

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
Locator = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str
    state: str
    properties: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AdbReport:
    available: bool
    executable: str | None
    version: str | None
    error: Diagnostic | None
    devices: tuple[Device, ...]


def parse_device_listing(stdout: str) -> tuple[Device, ...]:
    """Parse 'adb devices -l' without treating daemon messages as devices."""
    devices: list[Device] = []
    for original in stdout.splitlines():
        line = original.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        state = parts[1]
        properties_start = 2
        if len(parts) >= 3 and state == "no" and parts[2] == "permissions":
            state = "no_permissions"
            properties_start = 3
        if state not in ALLOWED_STATES:
            continue
        properties: dict[str, str] = {}
        for part in parts[properties_start:]:
            if ":" in part:
                name, value = part.split(":", 1)
                if name and value:
                    properties[name] = value
        devices.append(Device(device_id=parts[0], state=state, properties=properties))
    return tuple(devices)


def _execute(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout_s,
    )


def _version(stdout: str) -> str | None:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Version "):
            return stripped.removeprefix("Version ")
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Android Debug Bridge version "):
            return stripped.removeprefix("Android Debug Bridge version ")
    return None


def _clean_error(stderr: str) -> str:
    # Avoid returning uncontrolled command output: diagnostics must be bounded.
    return (stderr.strip().splitlines() or ["ADB returned a non-zero status"])[0][:240]


class AdbClient:
    """ADB inspector with injectable executable lookup and process runner."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        locator: Locator = shutil.which,
        runner: Runner = _execute,
        timeout_s: float = 5.0,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._executable = executable
        self._locator = locator
        self._runner = runner
        self._timeout_s = timeout_s

    def inspect(self) -> AdbReport:
        path = self._executable or self._locator("adb")
        if path is None:
            return AdbReport(
                available=False,
                executable=None,
                version=None,
                error=Diagnostic("ADB_NOT_FOUND", "Install Android Platform Tools to enable ADB."),
                devices=(),
            )

        try:
            version_result = self._runner([path, "version"], self._timeout_s)
            if version_result.returncode != 0:
                return AdbReport(
                    available=False,
                    executable=path,
                    version=None,
                    error=Diagnostic("ADB_VERSION_FAILED", _clean_error(version_result.stderr)),
                    devices=(),
                )

            list_result = self._runner([path, "devices", "-l"], self._timeout_s)
            if list_result.returncode != 0:
                return AdbReport(
                    available=True,
                    executable=path,
                    version=_version(version_result.stdout),
                    error=Diagnostic("ADB_LIST_FAILED", _clean_error(list_result.stderr)),
                    devices=(),
                )
        except subprocess.TimeoutExpired:
            return AdbReport(
                available=False,
                executable=path,
                version=None,
                error=Diagnostic(
                    "ADB_TIMEOUT", "ADB did not respond within the configured timeout."
                ),
                devices=(),
            )
        except OSError:
            return AdbReport(
                available=False,
                executable=path,
                version=None,
                error=Diagnostic("ADB_EXEC_FAILED", "ADB executable could not be launched."),
                devices=(),
            )

        return AdbReport(
            available=True,
            executable=path,
            version=_version(version_result.stdout),
            error=None,
            devices=parse_device_listing(list_result.stdout),
        )

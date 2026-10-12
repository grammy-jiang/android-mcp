"""Conservative, fixed-path Host developer toolchain inventory.

This provider executes *only* bounded, version-only CLI probes. The public
MCP Tool takes no executable, path, flag, license, or installation arguments.
Never discover executables from an attacker-controlled PATH.
"""

from __future__ import annotations

import json
import os
import platform
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.command_runner import OutputLimitExceeded, RunResult, bounded_run

TOOL_IDS = ("adb", "fastboot", "java", "gradle", "sdk")
OUTPUT_LIMIT_BYTES = 65536
MAX_SDK_ENTRIES = 128
_VERSION_PATTERNS = {
    "adb": re.compile(r"^Version ([0-9][0-9A-Za-z.+-]{0,63})$", re.MULTILINE),
    "fastboot": re.compile(r"^fastboot version ([0-9][0-9A-Za-z.+-]{0,63})$", re.MULTILINE),
    "java": re.compile(r'^(?:openjdk|java) version "([0-9][0-9A-Za-z.+-]{0,63})"', re.MULTILINE),
    "gradle": re.compile(r"^Gradle ([0-9]+(?:\.[0-9]+){1,3})$", re.MULTILINE),
}
_FIXED_FLAGS = {
    "adb": ("version",),
    "fastboot": ("--version",),
    "java": ("-version",),
    "gradle": ("--version",),
}
Runner = Callable[[Sequence[str], float, int], RunResult]


def get_toolchain_output_schema() -> dict[str, Any]:
    """Host-only v1 Tool response Schema; shared Native contracts stay unchanged."""
    resource = files("android_mcp_host.wire_schemas").joinpath(
        "host-toolchain-inventory.v1.schema.json"
    )
    data: Any = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid Host toolchain inventory schema")
    return data


def _state(available: bool, runnable: bool, version: str | None, reason: str) -> dict[str, Any]:
    return {
        "available": available,
        "runnable": runnable,
        "version": version,
        "reason": reason,
    }


def _candidate_paths(name: str, sdk: Path) -> tuple[Path, ...]:
    # These are trusted installation locations, not values derived from PATH.
    directories = (
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
    )
    if name == "adb":
        return (*tuple(folder / "adb" for folder in directories), sdk / "platform-tools" / "adb")
    if name == "fastboot":
        return (
            *tuple(folder / "fastboot" for folder in directories),
            sdk / "platform-tools" / "fastboot",
        )
    if name == "java":
        return (
            Path("/opt/homebrew/opt/openjdk@17/bin/java"),
            *tuple(folder / "java" for folder in directories),
        )
    if name == "gradle":
        return tuple(folder / "gradle" for folder in directories)
    raise ValueError("Unknown fixed executable identifier")


def _version(name: str, stdout: str, stderr: str) -> str | None:
    combined = stdout + "\n" + stderr
    match = _VERSION_PATTERNS[name].search(combined)
    return match.group(1) if match else None


class ToolchainInventory:
    """Probe fixed Host-owned executables and SDK state without modifications."""

    def __init__(
        self,
        *,
        paths: Mapping[str, Path] | None = None,
        sdk_root: Path | None = None,
        runner: Runner = bounded_run,
        timeout_s: float = 3.0,
    ) -> None:
        if not 0 < timeout_s <= 5:
            raise ValueError("Toolchain probe timeout must be between 0 and 5 seconds")
        if paths is not None and any(name not in _FIXED_FLAGS for name in paths):
            raise ValueError("Unknown fixed Host tool identifier")
        if sdk_root is None:
            sdk_root = (
                Path.home() / "Library/Android/sdk"
                if platform.system() == "Darwin"
                else Path.home() / "Android/Sdk"
            )
        if not sdk_root.is_absolute():
            raise ValueError("SDK root must be an absolute Host-trusted path")
        if paths is not None and any(not path.is_absolute() for path in paths.values()):
            raise ValueError("Executable paths must be absolute Host-trusted paths")
        self._paths = dict(paths) if paths is not None else None
        self._sdk_root = sdk_root
        self._runner = runner
        self._timeout_s = timeout_s

    def _selected_path(self, name: str) -> Path | None:
        if self._paths is not None:
            return self._paths.get(name)
        for candidate in _candidate_paths(name, self._sdk_root):
            # We do not look in PATH. A candidate file may be a trusted
            # package-manager symlink; _probe_cli verifies its target.
            try:
                candidate.stat()
            except OSError:
                continue
            return candidate
        return None

    def _probe_cli(self, name: str) -> dict[str, Any]:
        path = self._selected_path(name)
        if path is None:
            return _state(False, False, None, "NOT_INSTALLED")
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return _state(False, False, None, "NOT_INSTALLED")
        except PermissionError:
            return _state(False, False, None, "PERMISSION_DENIED")
        except OSError:
            return _state(False, False, None, "EXEC_FAILED")
        if not stat.S_ISREG(mode) or not mode & 0o111:
            return _state(True, False, None, "NOT_EXECUTABLE")
        if not os.access(path, os.X_OK):
            return _state(True, False, None, "PERMISSION_DENIED")
        try:
            result = self._runner(
                [str(path), *_FIXED_FLAGS[name]], self._timeout_s, OUTPUT_LIMIT_BYTES
            )
        except subprocess.TimeoutExpired:
            return _state(True, False, None, "TIMEOUT")
        except OutputLimitExceeded:
            return _state(True, False, None, "OUTPUT_LIMIT")
        except PermissionError:
            return _state(True, False, None, "PERMISSION_DENIED")
        except OSError:
            return _state(True, False, None, "EXEC_FAILED")
        except (ValueError, RuntimeError):
            return _state(True, False, None, "PROBE_FAILED")
        if (
            result.truncated
            or len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
            > OUTPUT_LIMIT_BYTES
        ):
            return _state(True, False, None, "OUTPUT_LIMIT")
        if result.returncode != 0:
            return _state(True, False, None, "NONZERO_EXIT")
        version = _version(name, result.stdout, result.stderr)
        if version is None:
            return _state(True, False, None, "MALFORMED_VERSION")
        return _state(True, True, version, "OK")

    def _probe_sdk(self) -> dict[str, Any]:
        try:
            if not self._sdk_root.exists():
                return _state(False, False, None, "NOT_INSTALLED")
            if not self._sdk_root.is_dir():
                return _state(True, False, None, "NOT_EXECUTABLE")
            platform_dir = self._sdk_root / "platforms"
            if not platform_dir.is_dir():
                return _state(True, False, None, "SDK_PLATFORM_NOT_FOUND")
            versions: list[int] = []
            with os.scandir(platform_dir) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= MAX_SDK_ENTRIES:
                        return _state(True, False, None, "OUTPUT_LIMIT")
                    match = re.fullmatch(r"android-([1-9][0-9]?)", entry.name)
                    if match is None or not entry.is_dir(follow_symlinks=False):
                        continue
                    jar = Path(entry.path) / "android.jar"
                    if jar.is_file() and jar.stat().st_size > 0:
                        versions.append(int(match.group(1)))
        except PermissionError:
            return _state(False, False, None, "PERMISSION_DENIED")
        except OSError:
            return _state(False, False, None, "EXEC_FAILED")
        if not versions:
            return _state(True, False, None, "SDK_PLATFORM_NOT_FOUND")
        return _state(True, True, str(max(versions)), "OK")

    def inspect(self) -> dict[str, object]:
        tools = {
            name: self._probe_sdk() if name == "sdk" else self._probe_cli(name) for name in TOOL_IDS
        }
        ready_count = sum(bool(item["runnable"]) for item in tools.values())
        status = (
            "ok" if ready_count == len(TOOL_IDS) else "partial" if ready_count else "unavailable"
        )
        return {
            "schema_version": 1,
            "runtime": "host",
            "status": status,
            "tools": tools,
        }

"""Read-only Host Android SDK/NDK/JDK/Gradle preflight with fail-closed paths.

Public MCP calls take zero arguments, install nothing and never accept terms.
This is an observation of local prerequisites, not a build authorization.
"""

from __future__ import annotations

import json
import os
import platform
import re
import stat
import subprocess
import zipfile
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.command_runner import OutputLimitExceeded, RunResult, bounded_run

MAX_METADATA_BYTES = 8192
MAX_PACKAGE_ENTRIES = 64
OUTPUT_BYTES = 65536
_KEYS = (
    "jdk17",
    "sdk_platform",
    "build_tools",
    "gradle",
    "emulator",
    "ndk",
    "cmake",
    "apkanalyzer_sdk",
    "apkanalyzer_homebrew",
)
_SDK_VERSION = "36"
_BUILD_TOOLS = "36.0.0"
_SEMVER = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}\Z", re.ASCII)
_JDK = re.compile(r'(?:openjdk|java) version "([0-9][0-9A-Za-z.+_-]{0,63})"', re.ASCII)
_GRADLE = re.compile(r"(?m)^Gradle ([0-9]+(?:\.[0-9]+){1,3})$", re.ASCII)
_EMULATOR = re.compile(r"(?m)^Android emulator version ([0-9]+(?:\.[0-9]+){1,3})", re.ASCII)
_CLANG = re.compile(r"\bclang version ([0-9]+(?:\.[0-9]+){1,3})", re.ASCII)
_CMAKE = re.compile(r"(?m)^cmake version ([0-9]+(?:\.[0-9]+){1,3})$", re.ASCII)
_ANALYZER = re.compile(r"(?m)^apkanalyzer ([0-9]+(?:\.[0-9]+){1,3})$", re.ASCII)
_REVISON = re.compile(r"(?m)^Pkg\.Revision\s*=\s*([0-9]+(?:\.[0-9]+){1,3})\s*$", re.ASCII)
Runner = Callable[[Sequence[str], float, int], RunResult]
# Deliberately do not inherit JAVA_HOME, JAVA_TOOL_OPTIONS, ANDROID_HOME,
# GRADLE_USER_HOME, LD_PRELOAD or a potentially hostile caller PATH.
_SAFE_PROBE_ENV = {
    "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
    "LANG": "C",
    "LC_ALL": "C",
}


def _safe_run(argv: Sequence[str], timeout_s: float, byte_limit: int) -> RunResult:
    return bounded_run(argv, timeout_s, byte_limit, env=_SAFE_PROBE_ENV)


def get_sdk_ndk_output_schema() -> dict[str, Any]:
    """Read the packaged Host-only workstation inventory schema."""
    result: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-sdk-ndk-inventory.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(result, dict):
        raise ValueError("Invalid packaged SDK/NDK inventory schema")
    return result


def _state(state: str, reason: str, version: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "reason": reason,
        "version": version,
        "installed": state in {"runnable", "installed_unusable"},
        "runnable": state == "runnable",
    }


def _unavailable(reason: str = "NOT_INSTALLED") -> dict[str, Any]:
    return _state("not_installed" if reason == "NOT_INSTALLED" else "installed_unusable", reason)


def _version_parts(value: str) -> tuple[int, ...] | None:
    if not _SEMVER.fullmatch(value):
        return None
    return tuple(int(part) for part in value.split("."))


def _fixed_binary(name: str) -> tuple[Path, ...]:
    if name == "jdk17":
        return (
            Path("/opt/homebrew/opt/openjdk@17/bin/java"),
            Path("/Library/Java/JavaVirtualMachines/openjdk-17.jdk/Contents/Home/bin/java"),
            Path("/usr/lib/jvm/java-17-openjdk-arm64/bin/java"),
        )
    if name == "gradle":
        return (
            Path("/opt/homebrew/bin/gradle"),
            Path("/usr/local/bin/gradle"),
            Path("/usr/bin/gradle"),
        )
    if name == "apkanalyzer_homebrew":
        return (Path("/opt/homebrew/bin/apkanalyzer"), Path("/usr/local/bin/apkanalyzer"))
    raise ValueError("Unsupported fixed workstation CLI")


def _host_tag(system: str, architecture: str) -> str | None:
    if system == "Darwin" and architecture == "arm64":
        return "darwin-arm64"
    if system == "Darwin" and architecture == "x86_64":
        return "darwin-x86_64"
    if system == "Linux" and architecture in {"aarch64", "arm64"}:
        return "linux-aarch64"
    if system == "Linux" and architecture == "x86_64":
        return "linux-x86_64"
    return None


class SdkNdkInventory:
    """Trusted local configuration only: no executable overrides in MCP args."""

    def __init__(
        self,
        *,
        sdk_root: Path | None = None,
        fixed_binaries: Mapping[str, Path] | None = None,
        runner: Runner = _safe_run,
        system: str | None = None,
        architecture: str | None = None,
        timeout_s: float = 3.0,
    ) -> None:
        if not 0 < timeout_s <= 5:
            raise ValueError("Version probe deadline must be 0–5 seconds")
        if fixed_binaries is not None and any(
            name not in {"jdk17", "gradle", "apkanalyzer_homebrew"} for name in fixed_binaries
        ):
            raise ValueError("Unrecognized fixed binary identifier")
        if sdk_root is None:
            sdk_root = (
                Path.home() / "Library/Android/sdk"
                if (system or platform.system()) == "Darwin"
                else Path.home() / "Android/Sdk"
            )
        if not sdk_root.is_absolute() or (
            fixed_binaries is not None
            and any(not path.is_absolute() for path in fixed_binaries.values())
        ):
            raise ValueError("Trusted SDK and executable paths must be absolute")
        self._sdk = sdk_root
        self._fixed = dict(fixed_binaries) if fixed_binaries is not None else None
        self._runner = runner
        self._timeout = timeout_s
        self._system = system or platform.system()
        self._architecture = architecture or platform.machine()

    def _safe_sdk(self, path: Path) -> bool:
        """Forbid symlinks anywhere under the selected SDK root."""
        try:
            relative = path.relative_to(self._sdk)
            nodes = (
                self._sdk,
                *tuple(
                    self._sdk / Path(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1)
                ),
            )
            return all(not node.is_symlink() for node in nodes)
        except (ValueError, OSError):
            return False

    def _sdk_state(self) -> dict[str, Any]:
        try:
            if self._sdk.is_symlink():
                return _state("path_rejected", "SDK_ROOT_SYMLINK")
            if not self._sdk.exists():
                return _unavailable()
            if not self._sdk.is_dir():
                return _unavailable("SDK_ROOT_INVALID")
            return _state("runnable", "OK")
        except PermissionError:
            return _unavailable("PERMISSION_DENIED")
        except OSError:
            return _unavailable("EXEC_FAILED")

    def _binary(self, path: Path | None, *, sdk_owned: bool = False) -> dict[str, Any]:
        if path is None:
            return _unavailable()
        if sdk_owned and not self._safe_sdk(path):
            return _state("path_rejected", "UNTRUSTED_SYMLINK")
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return _unavailable()
        except PermissionError:
            return _unavailable("PERMISSION_DENIED")
        except OSError:
            return _unavailable("EXEC_FAILED")
        if not stat.S_ISREG(mode) or mode & 0o111 == 0:
            return _unavailable("NOT_EXECUTABLE")
        if not os.access(path, os.X_OK):
            return _unavailable("PERMISSION_DENIED")
        return _state("runnable", "OK")

    def _selected_binary(self, name: str) -> Path | None:
        if self._fixed is not None:
            return self._fixed.get(name)
        for candidate in _fixed_binary(name):
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _probe(
        self,
        path: Path | None,
        flags: tuple[str, ...],
        expression: re.Pattern[str],
        *,
        sdk_owned: bool = False,
        expected: str | None = None,
        minimum_version: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        state = self._binary(path, sdk_owned=sdk_owned)
        if not state["runnable"] or path is None:
            return state
        try:
            result = self._runner([str(path), *flags], self._timeout, OUTPUT_BYTES)
        except subprocess.TimeoutExpired:
            return _unavailable("TIMEOUT")
        except OutputLimitExceeded:
            return _unavailable("OUTPUT_LIMIT")
        except PermissionError:
            return _unavailable("PERMISSION_DENIED")
        except (OSError, ValueError, RuntimeError):
            return _unavailable("EXEC_FAILED")
        if (
            not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
            or result.truncated
            or len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
            > OUTPUT_BYTES
        ):
            return _unavailable("OUTPUT_LIMIT")
        if result.returncode != 0:
            return _unavailable("NONZERO_EXIT")
        match = expression.search(result.stdout + "\n" + result.stderr)
        if match is None:
            return _unavailable("MALFORMED_VERSION")
        version = match.group(1)
        if expected is not None and version.split(".")[0] != expected:
            return _unavailable("VERSION_MISMATCH")
        if minimum_version is not None:
            parts = _version_parts(version)
            if parts is None or parts < minimum_version:
                return _unavailable("VERSION_MISMATCH")
        return _state("runnable", "OK", version)

    def _sdk_platform(self) -> dict[str, Any]:
        path = self._sdk / "platforms" / "android-36" / "android.jar"
        if not self._safe_sdk(path):
            return _state("path_rejected", "UNTRUSTED_SYMLINK")
        try:
            if not path.is_file():
                return _unavailable()
            if not 0 < path.stat().st_size <= 1_000_000_000:
                return _unavailable("MISSING_ARTIFACT")
            if not zipfile.is_zipfile(path):
                return _unavailable("MISSING_ARTIFACT")
            return _state("runnable", "OK", _SDK_VERSION)
        except PermissionError:
            return _unavailable("PERMISSION_DENIED")
        except OSError:
            return _unavailable("EXEC_FAILED")

    def _build_tools(self) -> dict[str, Any]:
        folder = self._sdk / "build-tools" / _BUILD_TOOLS
        metadata_path = folder / "source.properties"
        if not self._safe_sdk(metadata_path):
            return _state("path_rejected", "UNTRUSTED_SYMLINK")
        try:
            if metadata_path.stat().st_size > MAX_METADATA_BYTES:
                return _unavailable("OUTPUT_LIMIT")
            metadata = metadata_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _unavailable("MISSING_ARTIFACT")
        except (UnicodeError, PermissionError, OSError):
            return _unavailable("EXEC_FAILED")
        revision = _REVISON.search(metadata)
        if revision is None:
            return _unavailable("MALFORMED_VERSION")
        if revision.group(1) != _BUILD_TOOLS:
            return _unavailable("VERSION_MISMATCH")
        names = ("aapt2", "apksigner", "zipalign", "d8")
        states = [self._binary(folder / name, sdk_owned=True) for name in names]
        if all(state["runnable"] for state in states):
            return _state("runnable", "OK", _BUILD_TOOLS)
        return next(state for state in states if not state["runnable"])

    def _sdk_versions(self, name: str) -> tuple[list[Path], str | None]:
        folder = self._sdk / name
        if not self._safe_sdk(folder):
            return [], "UNTRUSTED_SYMLINK"
        try:
            if not folder.is_dir():
                return [], None
            versions: list[tuple[tuple[int, ...], Path]] = []
            with os.scandir(folder) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_PACKAGE_ENTRIES:
                        return [], "OUTPUT_LIMIT"
                    if entry.is_symlink():
                        return [], "UNTRUSTED_SYMLINK"
                    parts = _version_parts(entry.name)
                    if parts is not None and entry.is_dir(follow_symlinks=False):
                        versions.append((parts, Path(entry.path)))
            versions.sort(reverse=True)
            return [p for _, p in versions], None
        except PermissionError:
            return [], "PERMISSION_DENIED"
        except OSError:
            return [], "EXEC_FAILED"

    def _ndk(self) -> dict[str, Any]:
        folders, error = self._sdk_versions("ndk")
        if error is not None:
            return _unavailable(error)
        if not folders:
            return _unavailable()
        tag = _host_tag(self._system, self._architecture)
        if tag is None:
            return _state("unsupported_host", "UNSUPPORTED_HOST")
        folder = folders[0]
        source = folder / "source.properties"
        if not self._safe_sdk(source):
            return _state("path_rejected", "UNTRUSTED_SYMLINK")
        try:
            if source.stat().st_size > MAX_METADATA_BYTES:
                return _unavailable("OUTPUT_LIMIT")
            metadata = source.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _unavailable("MISSING_ARTIFACT")
        except (UnicodeError, PermissionError, OSError):
            return _unavailable("EXEC_FAILED")
        match = _REVISON.search(metadata)
        if match is None:
            return _unavailable("MALFORMED_VERSION")
        if match.group(1) != folder.name:
            return _unavailable("VERSION_MISMATCH")
        clang = folder / "toolchains" / "llvm" / "prebuilt" / tag / "bin" / "clang"
        state = self._probe(clang, ("--version",), _CLANG, sdk_owned=True)
        if state["runnable"]:
            return _state("runnable", "OK", match.group(1))
        return state

    def _cmake(self) -> dict[str, Any]:
        folders, error = self._sdk_versions("cmake")
        if error is not None:
            return _unavailable(error)
        if not folders:
            return _unavailable()
        version = folders[0].name
        state = self._probe(folders[0] / "bin" / "cmake", ("--version",), _CMAKE, sdk_owned=True)
        if not state["runnable"]:
            return state
        if state["version"] != version:
            return _unavailable("VERSION_MISMATCH")
        return state

    def inspect(self) -> dict[str, Any]:
        """Report bounded independent states; never read licenses or install tools."""
        sdk = self._sdk_state()
        if sdk["runnable"]:
            sdk_items = {
                "sdk_platform": self._sdk_platform(),
                "build_tools": self._build_tools(),
                "emulator": self._probe(
                    self._sdk / "emulator" / "emulator", ("-version",), _EMULATOR, sdk_owned=True
                ),
                "ndk": self._ndk(),
                "cmake": self._cmake(),
                "apkanalyzer_sdk": self._probe(
                    self._sdk / "cmdline-tools" / "latest" / "bin" / "apkanalyzer",
                    ("--version",),
                    _ANALYZER,
                    sdk_owned=True,
                ),
            }
        else:
            sdk_items = {
                name: dict(sdk)
                for name in _KEYS
                if name not in {"jdk17", "gradle", "apkanalyzer_homebrew"}
            }
        values = {
            "jdk17": self._probe(
                self._selected_binary("jdk17"), ("-version",), _JDK, expected="17"
            ),
            **sdk_items,
            "gradle": self._probe(
                self._selected_binary("gradle"),
                ("--version",),
                _GRADLE,
                minimum_version=(9, 6),
            ),
            "apkanalyzer_homebrew": self._probe(
                self._selected_binary("apkanalyzer_homebrew"), ("--version",), _ANALYZER
            ),
        }
        build_ready = all(
            values[name]["runnable"] for name in ("jdk17", "sdk_platform", "build_tools", "gradle")
        )
        count = sum(bool(value["runnable"]) for value in values.values())
        status = "ok" if count == len(_KEYS) else "partial" if count else "unavailable"
        return {
            "schema_version": 1,
            "runtime": "host",
            "status": status,
            "build_prerequisites_present": build_ready,
            "build_authorized": False,
            "sdk_licenses_verified": False,
            "tools": values,
        }

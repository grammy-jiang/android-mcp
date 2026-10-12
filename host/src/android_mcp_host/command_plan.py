"""Compile validated, typed Android engineering requests into fixed ADB argv.

No arbitrary remote-shell strings, host executable, APK root or command options
are accepted from an MCP caller. All Java identifiers use a conservative ASCII
character set because `adb shell` may pass arguments through a remote shell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANDROID_PACKAGE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+\Z", re.ASCII)
# ADB shell may expand $ in an unquoted component; never accept it in a runner.
JAVA_CLASS_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z", re.ASCII)
MAX_APK_BYTES = 2 * 1024**3


@dataclass(frozen=True, slots=True)
class Plan:
    kind: str
    argv_suffix: tuple[str, ...]
    mutating: bool
    timeout_s: float
    target: str


@dataclass(frozen=True, slots=True)
class PlanError:
    code: str
    message: str


def _fields_match(action: dict[str, Any], required: set[str], optional: set[str]) -> bool:
    return required <= action.keys() and set(action) <= required | optional


def _check_apk(path_value: object, allowed_roots: tuple[Path, ...]) -> Path | PlanError:
    if not isinstance(path_value, str) or not path_value or "\x00" in path_value:
        return PlanError("INVALID_APK_PATH", "Provide an absolute APK file path")
    untrusted = Path(path_value)
    if not untrusted.is_absolute() or untrusted.suffix.lower() != ".apk":
        return PlanError("INVALID_APK_PATH", "Provide an absolute .apk file path")
    # The default Host has no approved APK directories. Refuse uniformly
    # before touching the filesystem, so callers cannot probe path existence.
    if not allowed_roots:
        return PlanError("APK_NOT_ALLOWED", "No APK directories are approved")
    try:
        if untrusted.is_symlink():
            return PlanError("APK_NOT_ALLOWED", "Symlink APK files are not allowed")
        path = untrusted.resolve(strict=True)
        if not path.is_file():
            return PlanError("INVALID_APK_PATH", "APK must be a regular file")
        safe_roots = [r.resolve(strict=True) for r in allowed_roots]
        if not any(path.is_relative_to(r) for r in safe_roots):
            return PlanError("APK_NOT_ALLOWED", "APK is outside approved local directories")
        size = path.stat().st_size
        if size < 4 or size > MAX_APK_BYTES:
            return PlanError("INVALID_APK", "APK file size is invalid")
        with path.open("rb") as handle:
            signature = handle.read(4)
        if signature != b"PK\x03\x04":
            return PlanError("INVALID_APK", "APK is not a ZIP-format archive")
    except (OSError, RuntimeError):
        return PlanError("INVALID_APK_PATH", "APK path cannot be verified")
    return path


def prepare_action(
    raw: object,
    *,
    allowed_apk_roots: tuple[Path, ...] = (),
) -> Plan | PlanError:
    """Reject unknown keys and unsafe values *before* any external command."""
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        return PlanError("INVALID_ACTION", "Expected one typed action object")
    action: dict[str, Any] = raw
    kind = action["type"]
    if kind == "logcat_snapshot":
        if not _fields_match(action, {"type"}, {"lines"}):
            return PlanError("INVALID_ARGUMENTS", "Only lines is supported for logcat")
        lines = action.get("lines", 200)
        if type(lines) is not int or not 10 <= lines <= 2000:
            return PlanError("INVALID_ARGUMENTS", "Log lines must be an integer from 10 to 2000")
        return Plan(
            kind,
            ("logcat", "-d", "-t", str(lines), "-v", "threadtime"),
            False,
            15.0,
            "logcat buffer",
        )
    if kind == "package_details":
        if not _fields_match(action, {"type", "package"}, set()):
            return PlanError("INVALID_ARGUMENTS", "Package details require one package")
        package = action["package"]
        if (
            not isinstance(package, str)
            or len(package) > 200
            or not ANDROID_PACKAGE_RE.fullmatch(package)
        ):
            return PlanError("INVALID_PACKAGE", "Invalid Android package identifier")
        return Plan(kind, ("shell", "dumpsys", "package", package), False, 15.0, package)
    if kind == "instrument_test":
        if not _fields_match(action, {"type", "package", "runner"}, set()):
            return PlanError("INVALID_ARGUMENTS", "Instrumentation needs package and runner")
        package, runner = action["package"], action["runner"]
        if (
            not isinstance(package, str)
            or len(package) > 200
            or not ANDROID_PACKAGE_RE.fullmatch(package)
            or not isinstance(runner, str)
            or len(runner) > 256
            or not JAVA_CLASS_RE.fullmatch(runner)
        ):
            return PlanError("INVALID_COMPONENT", "Invalid instrumentation component")
        component = f"{package}/{runner}"
        return Plan(kind, ("shell", "am", "instrument", "-w", component), True, 120.0, component)
    if kind == "install_apk":
        if not _fields_match(action, {"type", "apk_path"}, {"replace", "allow_test"}):
            return PlanError("INVALID_ARGUMENTS", "APK install accepts path and safe flags")
        replace, allow_test = action.get("replace", True), action.get("allow_test", False)
        if type(replace) is not bool or type(allow_test) is not bool:
            return PlanError("INVALID_ARGUMENTS", "APK install flags must be booleans")
        path = _check_apk(action["apk_path"], allowed_apk_roots)
        if isinstance(path, PlanError):
            return path
        flags = (("-r",) if replace else ()) + (("-t",) if allow_test else ())
        return Plan(kind, ("install", *flags, str(path)), True, 120.0, path.name)
    return PlanError("UNKNOWN_OPERATION", "Operation is not in the approved command registry")

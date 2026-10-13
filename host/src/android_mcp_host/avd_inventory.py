"""Opt-in Host AVD inventory: local metadata only, never start/stop an emulator."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.avd_inventory_support import (
    avd_metadata,
    lock_pid,
    trusted_dir,
    valid_name,
)
from android_mcp_host.command_runner import RunResult, bounded_run

MAX_AVDS = 32
MAX_LIST_BYTES = 8192
MAX_PROCESS_BYTES = 4096
_TIME_LIMIT = 5.0
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
Runner = Callable[[Sequence[str], float, int], RunResult]
_ERRORS: dict[str, str] = {
    "INVALID_NAME": "AVD identifier is invalid",
    "AVD_NOT_FOUND": "AVD is unavailable",
    "EMULATOR_UNAVAILABLE": "Local Android emulator is unavailable",
    "AVD_ROOT_UNAVAILABLE": "Trusted local AVD store is unavailable",
    "EMULATOR_TIMEOUT": "Emulator inventory timed out",
    "EMULATOR_FAILED": "Emulator inventory command failed",
    "EMULATOR_LIST_INVALID": "Emulator returned malformed AVD inventory",
    "METADATA_INVALID": "AVD configuration metadata is unavailable",
}


def get_avd_output_schema() -> dict[str, Any]:
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-avd-inventory.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid Host AVD inventory schema")
    return value


def _result(status: str, avds: list[dict[str, Any]], issues: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": "host",
        "status": status,
        "avds": avds,
        "errors": [{"code": code, "message": _ERRORS[code]} for code in issues[:3]],
    }


def _safe_emulator(executable: Path) -> bool:
    if not executable.is_absolute() or ".." in executable.parts:
        return False
    try:
        if any(part.is_symlink() for part in (executable, *executable.parents)):
            return False
        info = executable.stat()
        return (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_size > 0
            and bool(info.st_mode & 0o111)
            and os.access(executable, os.X_OK)
        )
    except OSError:
        return False


def _run_local(argv: Sequence[str], timeout: float, limit: int) -> RunResult:
    return bounded_run(argv, timeout, limit, env=_ENV)


def _safe_list(value: RunResult) -> list[str] | None:
    if (
        not isinstance(value, RunResult)
        or value.returncode != 0
        or value.truncated
        or not isinstance(value.stdout, str)
        or len(value.stdout.encode("utf-8")) > MAX_LIST_BYTES
        or value.stderr
    ):
        return None
    names = [line.strip() for line in value.stdout.splitlines()]
    if len(names) > MAX_AVDS:
        return None
    if any(not valid_name(name) for name in names):
        return None
    if len({name.casefold() for name in names}) != len(names):
        return None
    return names


def _verified_process(result: RunResult, emulator: Path, name: str) -> bool:
    if (
        not isinstance(result, RunResult)
        or result.returncode != 0
        or result.truncated
        or result.stderr
        or not isinstance(result.stdout, str)
        or len(result.stdout.encode("utf-8")) > MAX_PROCESS_BYTES
    ):
        return False
    try:
        args = shlex.split(result.stdout.strip())
    except ValueError:
        return False
    if not args or not Path(args[0]).is_absolute() or ".." in Path(args[0]).parts:
        return False
    executable = Path(args[0])
    path_ok = executable == emulator or (
        emulator.parent / "qemu" in executable.parents
        and executable.name.startswith("qemu-system-")
    )
    if not path_ok:
        return False
    return any(args[i : i + 2] == ["-avd", name] for i in range(len(args) - 1))


class AvdInventory:
    """AVD metadata reader using only fixed list-avds and ps inspections."""

    def __init__(
        self,
        avd_root: Path,
        emulator_binary: Path,
        *,
        runner: Runner = _run_local,
        process_runner: Runner = _run_local,
        timeout_s: float = 3.0,
    ) -> None:
        if (
            not isinstance(avd_root, Path)
            or not isinstance(emulator_binary, Path)
            or not avd_root.is_absolute()
            or not emulator_binary.is_absolute()
            or ".." in avd_root.parts
            or ".." in emulator_binary.parts
            or len(str(avd_root)) > 1024
            or len(str(emulator_binary)) > 1024
        ):
            raise ValueError("AVD root and emulator must be operator-pinned absolute paths")
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= _TIME_LIMIT:
            raise ValueError("Invalid bounded emulator inspection deadline")
        self._root = avd_root
        self._binary = emulator_binary
        self._runner = runner
        self._process_runner = process_runner
        self._timeout = timeout_s

    def _process(self, path: Path, name: str) -> str:
        pid = lock_pid(path)
        if pid is None:
            return "stale_or_unverified"
        try:
            output = self._process_runner(
                ["/bin/ps", "-p", str(pid), "-ww", "-o", "args="],
                self._timeout,
                MAX_PROCESS_BYTES,
            )
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError):
            return "stale_or_unverified"
        if _verified_process(output, self._binary, name):
            return "verified_running"
        return "stale_or_unverified"

    def inspect(self, name: str | None = None) -> dict[str, Any]:
        """Return bounded AVD metadata without commands changing emulator state."""
        if name is not None and not valid_name(name):
            return _result("invalid", [], ["INVALID_NAME"])
        if not _safe_emulator(self._binary):
            return _result("unavailable", [], ["EMULATOR_UNAVAILABLE"])
        if not trusted_dir(self._root):
            return _result("unavailable", [], ["AVD_ROOT_UNAVAILABLE"])
        try:
            argv = [str(self._binary), "-list-avds"]
            if self._runner is _run_local:
                # Emulator honors an explicit AVD_HOME, never a caller's
                # environment variables or a guessed physical target.
                fixed_env = {
                    **_ENV,
                    "HOME": str(Path.home()),
                    "ANDROID_AVD_HOME": str(self._root),
                    "ANDROID_SDK_ROOT": str(self._binary.parent.parent),
                }
                response = bounded_run(argv, self._timeout, MAX_LIST_BYTES, env=fixed_env)
            else:
                response = self._runner(argv, self._timeout, MAX_LIST_BYTES)
        except subprocess.TimeoutExpired:
            return _result("unavailable", [], ["EMULATOR_TIMEOUT"])
        except (OSError, RuntimeError, ValueError):
            return _result("unavailable", [], ["EMULATOR_FAILED"])
        avd_names = _safe_list(response)
        if avd_names is None:
            return _result("invalid", [], ["EMULATOR_LIST_INVALID"])
        if name is not None:
            if name not in avd_names:
                return _result("not_found", [], ["AVD_NOT_FOUND"])
            avd_names = [name]
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        for avd in avd_names:
            record, avd_path = avd_metadata(self._root, avd)
            if record is None or avd_path is None:
                errors.append("METADATA_INVALID")
                continue
            record["running_state"] = self._process(avd_path, avd)
            records.append(record)
        return _result("partial" if errors else "ok", records, errors)

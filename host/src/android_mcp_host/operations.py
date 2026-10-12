"""Typed Host Android engineering actions with explicit policy/lease boundaries.

The default server can *observe* and preview installation/test actions, but it
cannot mutate any device. Authorizations, device leases and audit sinks must be
installed by trusted host configuration, never furnished by an MCP argument.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from android_mcp_host.security.coordinator import SecureMutationCoordinator

from android_mcp_host.adb import AdbClient
from android_mcp_host.command_plan import PlanError, prepare_action
from android_mcp_host.command_runner import RunResult, bounded_run
from android_mcp_host.device_guard import require_online, valid_device_id

OUTPUT_BYTE_LIMIT = 65536
MAX_RESULT_CHARS = 25000


class RunCommand(Protocol):
    def __call__(self, argv: list[str], timeout_s: float, byte_limit: int) -> RunResult: ...


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _safe_text_status(text: str) -> tuple[str, bool]:
    """Strip controls and distinguish a display cap from complete output."""
    clean = "".join(ch for ch in text if ch in "\n\r\t" or ord(ch) >= 32 and ord(ch) != 127)
    return clean[:MAX_RESULT_CHARS], len(clean) > MAX_RESULT_CHARS


def _safe_text(text: str) -> str:
    return _safe_text_status(text)[0]


def _result_body(result: RunResult) -> tuple[dict[str, object], bool]:
    safe, shortened = _safe_text_status(result.stdout)
    return {
        "exit_code": result.returncode,
        "stdout": safe,
        "truncated": result.truncated or shortened,
    }, shortened


def _diagnose(kind: str, result: RunResult) -> tuple[str, dict[str, str] | None]:
    if result.truncated:
        return "partial", _error("OUTPUT_LIMIT", "Output exceeded bounded capture")
    if result.returncode != 0:
        return "error", _error("ADB_OPERATION_FAILED", "ADB reported operation failure")
    output = result.stdout + "\n" + result.stderr
    if kind == "install_apk":
        if "Failure [" in output or "INSTALL_FAILED" in output:
            return "error", _error("APK_INSTALL_FAILED", "Android rejected APK installation")
        if not any(line.strip() == "Success" for line in output.splitlines()):
            return "partial", _error("APK_RESULT_UNCONFIRMED", "Install success was not confirmed")
    if kind == "instrument_test":
        if "INSTRUMENTATION_FAILED" in output or "FAILURES!!!" in output:
            return "error", _error("TEST_FAILED", "Instrumentation reported a failure")
        codes = [
            line.partition(":")[2].strip()
            for line in output.splitlines()
            if line.startswith("INSTRUMENTATION_CODE:")
        ]
        if codes and codes[-1] != "-1":
            return "error", _error("TEST_FAILED", "Instrumentation returned a failure code")
        if not codes or not any(line.strip().startswith("OK (") for line in output.splitlines()):
            return "partial", _error("TEST_RESULT_UNCONFIRMED", "Test success was not verified")
    return "ok", None


class OperationService:
    """No implicit device selection, model approvals or raw-shell passthrough."""

    def __init__(
        self,
        adb: AdbClient | None = None,
        *,
        adb_executable: str | None = None,
        allowed_apk_roots: tuple[Path, ...] = (),
        locate: Callable[[str], str | None] = shutil.which,
        runner: RunCommand = bounded_run,
        secure_coordinator: SecureMutationCoordinator | None = None,
    ) -> None:
        self._adb = adb if adb is not None else AdbClient()
        self._executable = adb_executable
        self._roots = allowed_apk_roots
        self._locate = locate
        self._runner = runner
        self._secure_coordinator = secure_coordinator
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, device_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(device_id, threading.Lock())

    def execute(
        self,
        device_id: str,
        action: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute one allowlisted action or return a reviewable non-mutating plan.

        All user inputs are validated before ADB discovery. Mutations always
        require a trusted injected SecureMutationCoordinator with verified
        operator grants, Host/Native leases and durable auditing.
        """
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id if isinstance(device_id, str) else "",
            "operation": (
                action["type"]
                if isinstance(action, dict) and isinstance(action.get("type"), str)
                else ""
            ),
            "status": "error",
            "mutating": False,
            "dry_run": dry_run if isinstance(dry_run, bool) else False,
            "command": [],
            "result": None,
            "errors": [],
        }
        if not valid_device_id(device_id):
            response["errors"].append(_error("INVALID_DEVICE_ID", "Invalid device identifier"))
            return response
        if type(dry_run) is not bool:
            response["errors"].append(_error("INVALID_DRY_RUN", "dry_run must be boolean"))
            return response
        plan = prepare_action(action, allowed_apk_roots=self._roots)
        if isinstance(plan, PlanError):
            response["errors"].append(_error(plan.code, plan.message))
            return response
        response["operation"] = plan.kind
        response["mutating"] = plan.mutating
        report = self._adb.inspect()
        problem = require_online(report, device_id)
        if problem is not None:
            response["errors"].append(problem)
            return response
        binary = self._executable or report.executable or self._locate("adb")
        if not binary:
            response["errors"].append(_error("ADB_NOT_FOUND", "ADB executable unavailable"))
            return response
        argv = [binary, "-s", device_id, *plan.argv_suffix]
        # The actual binary path is not rendered; the arguments are exact and
        # are never rejoined into a host shell command for execution.
        response["command"] = ["adb", *argv[1:]]
        if dry_run:
            response["status"] = "planned"
            return response
        lock = self._lock(device_id)
        if not lock.acquire(blocking=False):
            response["errors"].append(_error("DEVICE_BUSY", "Another Host action is active"))
            return response
        try:
            if plan.mutating and self._secure_coordinator is not None:
                # Only a trusted, host-constructed coordinator can enter this path.
                # It never accepts grants, public keys or leases as MCP arguments.
                outcome = self._secure_coordinator.perform(
                    device_id=device_id,
                    plan=plan,
                    binary=binary,
                    runner=self._runner,
                    output_byte_limit=OUTPUT_BYTE_LIMIT,
                )
                response["status"] = {
                    "completed": "ok",
                    "partial": "partial",
                    "blocked": "error",
                    "error": "error",
                }.get(outcome.status, "error")
                if outcome.result is not None:
                    response["result"], shortened = _result_body(outcome.result)
                    if shortened:
                        if response["status"] == "ok":
                            response["status"] = "partial"
                        response["errors"].append(
                            _error("OUTPUT_LIMIT", "Result shortened to response display budget")
                        )
                if outcome.code != "NONE":
                    response["errors"].append(
                        _error(outcome.code, "Secure operation did not fully complete")
                    )
                return response
            if plan.mutating:
                response["errors"].append(
                    _error("MUTATION_DISABLED", "Trusted mutation coordinator is not configured")
                )
                return response
            try:
                result = self._runner(argv, plan.timeout_s, OUTPUT_BYTE_LIMIT)
            except subprocess.TimeoutExpired:
                response["errors"].append(_error("OPERATION_TIMEOUT", "ADB action timed out"))
                return response
            except (OSError, ValueError):
                response["errors"].append(_error("OPERATION_EXEC_FAILED", "ADB action failed"))
                return response
            status, failure = _diagnose(plan.kind, result)
            response["status"] = status
            response["result"], shortened = _result_body(result)
            if failure is not None:
                response["errors"].append(failure)
            if shortened:
                if response["status"] == "ok":
                    response["status"] = "partial"
                if failure is None or failure["code"] != "OUTPUT_LIMIT":
                    response["errors"].append(
                        _error("OUTPUT_LIMIT", "Result shortened to response display budget")
                    )
            return response
        finally:
            lock.release()

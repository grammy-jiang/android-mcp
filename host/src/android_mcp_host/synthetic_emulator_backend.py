"""Pinned, fake-only subprocess backend for H3.c conformance testing.

This backend explicitly cannot execute Android's real emulator or manipulate
a connected Android device. It is not exposed through production CLI config.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

MAX_FIXTURE_BYTES = 16384
MAX_READINESS_BYTES = 4096
_MARKER = b"ANDROID-MCP-SYNTHETIC-EMULATOR-ONLY"


class SyntheticEmulatorError(Exception):
    """A fixed local fake child failed readiness or cleanup."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Synthetic emulator unavailable: {code}")


class SyntheticEmulatorBackend:
    """Start/stop only a pinned emulator-shaped fixture, never real QEMU."""

    def __init__(self, executable: Path, expected_sha256: str) -> None:
        if (
            not isinstance(executable, Path)
            or not executable.is_absolute()
            or executable.name != "mcp-fixture-emulator"
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError("Invalid pinned synthetic emulator fixture")
        self._binary = executable
        self._digest = expected_sha256

    def _verify_executable(self) -> bool:
        try:
            if any(part.is_symlink() for part in (self._binary, *self._binary.parents)):
                return False
            info = self._binary.stat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or not 0 < info.st_size <= MAX_FIXTURE_BYTES
                or info.st_nlink != 1
                or not info.st_mode & 0o111
            ):
                return False
            content = self._binary.read_bytes()
            return (
                content.startswith(b"#!/")
                and _MARKER in content[:256]
                and hashlib.sha256(content).hexdigest() == self._digest
            )
        except OSError:
            return False

    def launch(
        self, name: str, avd_root: Path, timeout_s: float
    ) -> tuple[subprocess.Popen[bytes], dict[str, Any]]:
        """Run one fixed fake argv with parent-death stdin pipe and bounded readiness."""
        if not self._verify_executable():
            raise SyntheticEmulatorError("UNTRUSTED_FIXTURE")
        env = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "ANDROID_AVD_HOME": str(avd_root),
            "ANDROID_MCP_SYNTHETIC_ONLY": "1",
        }
        argv = [
            str(self._binary),
            "-avd",
            name,
            "-no-window",
            "-no-audio",
            "-no-snapshot-save",
        ]
        try:
            child = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
                cwd=str(avd_root),
            )
        except OSError as error:
            raise SyntheticEmulatorError("SPAWN_FAILED") from error
        try:
            report = self._read_ready(child, timeout_s)
            if child.poll() is not None:
                raise SyntheticEmulatorError("PROCESS_EXITED")
            return child, report
        except BaseException:
            self.stop(child)
            raise

    @staticmethod
    def _read_ready(child: subprocess.Popen[bytes], timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        assert child.stdout is not None
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            while b"\n" not in output:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SyntheticEmulatorError("READINESS_TIMEOUT")
                events = selector.select(remaining)
                if not events:
                    raise SyntheticEmulatorError("READINESS_TIMEOUT")
                for event, _ in events:
                    part = os.read(event.fd, MAX_READINESS_BYTES + 1)
                    if not part:
                        raise SyntheticEmulatorError("PROCESS_EXITED")
                    output.extend(part)
                    if len(output) > MAX_READINESS_BYTES:
                        raise SyntheticEmulatorError("READINESS_LIMIT")
        try:
            value = json.loads(output.split(b"\n", 1)[0])
        except (ValueError, UnicodeError) as error:
            raise SyntheticEmulatorError("READINESS_REJECTED") from error
        if not isinstance(value, dict):
            raise SyntheticEmulatorError("READINESS_REJECTED")
        return value

    @staticmethod
    def is_running(child: subprocess.Popen[bytes]) -> bool:
        return child.poll() is None

    @staticmethod
    def stop(child: subprocess.Popen[bytes]) -> bool:
        """Only signal the live Popen child's own new session; never a caller PID."""
        try:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return False
        except (ProcessLookupError, OSError):
            return False
        finally:
            if child.stdin is not None:
                child.stdin.close()
            if child.stdout is not None:
                child.stdout.close()
        return child.poll() is not None

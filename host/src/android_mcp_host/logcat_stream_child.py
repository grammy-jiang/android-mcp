"""Bounded *test-only* finite Logcat fixture subprocess with group cleanup.

Not imported by production CLI. Never runs ADB: only an explicitly pinned
Python fixture script, without shell expansion or client-controlled argv.
"""

from __future__ import annotations

import os
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path
from threading import Event

from android_mcp_host.logcat_stream_support import MAX_RAW_BYTES
from android_mcp_host.synthetic_logcat_stream import StreamFrame


class SyntheticLogcatProcessReader:
    """Trusted test harness fixture subprocess; capped byte pipe and deadline."""

    def __init__(self, python: Path, script: Path) -> None:
        if not python.is_absolute() or not script.is_absolute():
            raise ValueError("Only absolute pinned Python synthetic fixtures are supported")
        try:
            real_python = python.resolve(strict=True)
            real_script = script.resolve(strict=True)
        except OSError as error:
            raise ValueError("Unknown trusted synthetic fixture") from error
        if (
            not real_python.name.startswith("python")
            or real_script.suffix != ".py"
            or not real_python.is_file()
            or not real_script.is_file()
            or script.is_symlink()
        ):
            raise ValueError("Only absolute pinned Python synthetic fixtures are supported")
        info = real_script.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("Untrusted Python synthetic fixture script")
        self._python = real_python
        self._script = real_script

    @staticmethod
    def _stop_group(process: subprocess.Popen[bytes]) -> None:
        """Always dispose of the exact isolated process group, including children."""
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

    def __call__(
        self,
        name: str,
        handle: str,
        lifecycle: str,
        maximum: int,
        max_bytes: int,
        timeout: float,
        stop: Event,
    ) -> StreamFrame:
        if (
            type(maximum) is not int
            or not 1 <= maximum <= 128
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_RAW_BYTES
            or type(timeout) not in (float, int)
            or not 0 < timeout <= 3.0
        ):
            raise ValueError("Untrusted synthetic fixture limits")
        started = time.monotonic()
        process = subprocess.Popen(
            [
                str(self._python),
                str(Path(__file__).resolve().with_name("logcat_stream_guard.py")),
                str(self._script),
                str(os.getpid()),
                repr(started + timeout),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        parts: list[bytes] = []
        total = 0
        try:
            assert process.stdout is not None
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if stop.is_set():
                        raise InterruptedError("Synthetic fixture capture stopped")
                    if time.monotonic() - started >= timeout:
                        raise subprocess.TimeoutExpired(["synthetic-logcat-fixture"], timeout)
                    ready = selector.select(timeout=0.04)
                    if not ready:
                        continue
                    chunk = os.read(process.stdout.fileno(), min(8192, max_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Synthetic fixture output cap exceeded")
                    parts.append(chunk)
            if process.wait(timeout=max(0.01, timeout - (time.monotonic() - started))) != 0:
                raise RuntimeError("Synthetic fixture returned unsuccessful exit")
            return StreamFrame(b"".join(parts), name, handle, lifecycle, True, True)
        finally:
            self._stop_group(process)
            if process.stdout is not None:
                process.stdout.close()

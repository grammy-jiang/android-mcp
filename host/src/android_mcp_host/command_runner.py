"""Bounded subprocess execution on macOS and Linux, without a shell.

ADB output is untrusted and can be arbitrarily large. Read both pipes in
parallel and terminate the entire new subprocess session at the byte cap or
on timeout, avoiding `subprocess.run(capture_output=True)` memory growth.
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class OutputLimitExceeded(Exception):
    """A subprocess produced more data than its read budget."""


@dataclass(frozen=True, slots=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool


def _end_process(process: subprocess.Popen[bytes]) -> None:
    # The launcher can exit while descendants keep stdout/stderr pipes open.
    # Clean the entire session even when the original parent has already exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2.0)


def bounded_run(
    argv: Sequence[str],
    timeout_s: float,
    byte_limit: int,
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> RunResult:
    """Capture limited bytes, killing the command if it exceeds resource limits."""
    if not 0 < timeout_s <= 180 or not 1024 <= byte_limit <= 262144:
        raise ValueError("Invalid execution limit")
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
        cwd=cwd,
    )
    captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_s
    truncated = False
    try:
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stderr is not None
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(list(argv), timeout_s)
                for event, _ in selector.select(remaining):
                    try:
                        chunk = os.read(event.fd, 8192)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(event.fileobj)
                        continue
                    used = sum(len(v) for v in captured.values())
                    room = byte_limit - used
                    if room <= len(chunk):
                        captured[event.data].extend(chunk[: max(0, room)])
                        truncated = True
                        break
                    captured[event.data].extend(chunk)
                if truncated:
                    break
        if truncated:
            _end_process(process)
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(argv), timeout_s)
            process.wait(timeout=remaining)
        return RunResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=bytes(captured["stdout"]).decode("utf-8", errors="replace"),
            stderr=bytes(captured["stderr"]).decode("utf-8", errors="replace"),
            truncated=truncated,
        )
    except BaseException:
        _end_process(process)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def completed_bounded(
    argv: Sequence[str], timeout_s: float, byte_limit: int
) -> subprocess.CompletedProcess[str]:
    """Bound stdout/stderr growth before creating a CompletedProcess facade."""
    result = bounded_run(argv, timeout_s, byte_limit)
    if result.truncated:
        raise OutputLimitExceeded("ADB output exceeded the capture budget")
    return subprocess.CompletedProcess(list(argv), result.returncode, result.stdout, result.stderr)

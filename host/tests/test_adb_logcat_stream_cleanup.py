"""Deterministic signal races against isolated, hardware-free fixture processes."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from test_adb_logcat_stream_child import assert_fixture_terminated, script
from test_adb_logcat_stream_jobs import NAME

from android_mcp_host.logcat_stream_child import SyntheticLogcatProcessReader


@contextmanager
def isolated_group(*, child: bool = False) -> Iterator[list[subprocess.Popen[bytes]]]:
    """Keep children reapable by pytest, even when the group leader exits first."""
    real_killpg = os.killpg
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for _ in range(2 if child else 1):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    process_group=processes[0].pid if processes else 0,
                )
            )
        assert os.getpgid(processes[0].pid) == processes[0].pid != os.getpgrp()
        yield processes
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        if processes:
            try:
                real_killpg(processes[0].pid, 0)
            except ProcessLookupError:
                pass
            else:
                pytest.fail("Synthetic process group survived test teardown")


@pytest.mark.parametrize("reaped", [False, True])
def test_permission_race_reaps_dead_group_and_allows_double_cleanup(
    monkeypatch: pytest.MonkeyPatch, reaped: bool
) -> None:
    with isolated_group() as (process,):
        real_killpg = os.killpg
        real_killpg(process.pid, signal.SIGKILL)
        if reaped:
            process.wait(timeout=2)

        def denied_kill(group: int, sig: int) -> None:
            assert group == process.pid
            if sig == signal.SIGKILL:
                raise PermissionError(errno.EPERM, "injected dead-group race")
            real_killpg(group, sig)

        monkeypatch.setattr(os, "killpg", denied_kill)
        SyntheticLogcatProcessReader._stop_group(process)
        SyntheticLogcatProcessReader._stop_group(process)
        assert process.returncode == -signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            real_killpg(process.pid, 0)


def test_permission_probe_can_race_before_group_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_group() as (process,):
        real_killpg = os.killpg
        process.kill()
        process.wait(timeout=2)
        probes = 0

        def race(group: int, sig: int) -> None:
            nonlocal probes
            assert group == process.pid
            if sig == 0:
                probes += 1
                if probes > 2:
                    return real_killpg(group, sig)
            raise PermissionError(errno.EPERM, "injected pending group removal")

        monkeypatch.setattr(os, "killpg", race)
        SyntheticLogcatProcessReader._stop_group(process)
        assert process.returncode == -signal.SIGKILL
        assert probes > 2


@pytest.mark.parametrize("leader_reaped", [False, True])
@pytest.mark.parametrize("probe_denied", [False, True])
def test_permission_error_on_live_group_fails_closed_even_with_reaped_leader(
    monkeypatch: pytest.MonkeyPatch, leader_reaped: bool, probe_denied: bool
) -> None:
    with isolated_group(child=True) as (leader, child):
        if leader_reaped:
            leader.kill()
            leader.wait(timeout=2)
        real_killpg = os.killpg
        denied = PermissionError(errno.EPERM, "injected live-group denial")

        def deny(group: int, sig: int) -> None:
            assert group == leader.pid != os.getpgrp()
            if sig == signal.SIGKILL or probe_denied:
                raise denied
            real_killpg(group, sig)

        monkeypatch.setattr(os, "killpg", deny)
        started = time.monotonic()
        with pytest.raises(PermissionError) as caught:
            SyntheticLogcatProcessReader._stop_group(leader)
        assert caught.value is denied
        assert time.monotonic() - started < 1.5
        assert child.poll() is None, "injection must leave a live child to detect"


def test_cleanup_kills_child_after_leader_reaped_and_is_repeatable() -> None:
    with isolated_group(child=True) as (leader, child):
        leader.kill()
        leader.wait(timeout=2)
        assert child.poll() is None
        SyntheticLogcatProcessReader._stop_group(leader)
        assert child.wait(timeout=2) == -signal.SIGKILL
        SyntheticLogcatProcessReader._stop_group(leader)


def test_reader_preserves_timeout_after_injected_watchdog_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "fixture-pid"
    fixture = script(
        tmp_path,
        "import os,time\nfrom pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
    )
    reader = SyntheticLogcatProcessReader(Path(sys.executable), fixture)
    real_spawn, real_killpg = subprocess.Popen, os.killpg
    processes: list[subprocess.Popen[bytes]] = []

    def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real_spawn(*args, **kwargs)
        processes.append(process)
        assert os.getpgid(process.pid) == process.pid != os.getpgrp()
        assert os.getsid(process.pid) == process.pid
        return process

    def watchdog_race(group: int, sig: int) -> None:
        assert group == processes[0].pid
        if sig == signal.SIGKILL:
            try:
                real_killpg(group, sig)
            except (ProcessLookupError, PermissionError):
                pass
            raise PermissionError(errno.EPERM, "injected watchdog won cleanup race")
        real_killpg(group, sig)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(os, "killpg", watchdog_race)
    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            reader(NAME, "fake-avd", "job_" + "x" * 32, 128, 65536, 0.5, threading.Event())
        assert caught.value.timeout == 0.5
        assert processes[0].returncode is not None
        assert processes[0].stdout is not None and processes[0].stdout.closed
        assert_fixture_terminated(int(pid_file.read_text()))
    finally:
        for process in processes:
            try:
                real_killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            process.wait(timeout=2)
            if process.stdout is not None:
                process.stdout.close()


@pytest.mark.parametrize("times_out", [False, True])
def test_reader_closes_pipe_even_when_group_cleanup_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, times_out: bool
) -> None:
    body = "import time; time.sleep(30)\n" if times_out else "pass\n"
    reader = SyntheticLogcatProcessReader(Path(sys.executable), script(tmp_path, body))
    real_spawn = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real_spawn(*args, **kwargs)
        processes.append(process)
        return process

    def deny(group: int, sig: int) -> None:
        assert group == processes[0].pid
        raise PermissionError(errno.EPERM, "injected unverifiable cleanup")

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(os, "killpg", deny)
    try:
        with pytest.raises(PermissionError) as caught:
            reader(NAME, "fake-avd", "job_" + "x" * 32, 128, 65536, 0.5, threading.Event())
        if times_out:
            assert isinstance(caught.value.__context__, subprocess.TimeoutExpired)
        assert processes[0].stdout is not None and processes[0].stdout.closed
    finally:
        for process in processes:
            process.wait(timeout=2)
            if process.stdout is not None:
                process.stdout.close()

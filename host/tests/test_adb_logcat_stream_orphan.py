"""H5.b independent fixture supervisor: parent-SIGKILL and deadline guarantees.

The guard lives outside the Host and kills its isolated process group even
if Python finally clauses never run. All real subprocesses are local fakes.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from android_mcp_host import logcat_stream_guard


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["script", "1", "500"],
        ["/absolute/test.py", "not-pid", "501"],
        ["/absolute/test.py", "45", "nan"],
        ["/absolute/test.py", "45", "inf"],
        ["/absolute/test.py", "45", "-1"],
        ["relative/test.py", "45", "501"],
        ["/absolute/test.py", "45", "520"],
    ],
)
def test_guard_rejects_unbounded_or_untrusted_invocation(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    monkeypatch.setattr(logcat_stream_guard.os, "getpgrp", lambda: 100)
    monkeypatch.setattr(logcat_stream_guard.os, "getpid", lambda: 100)
    monkeypatch.setattr(logcat_stream_guard.os, "getppid", lambda: 45)
    monkeypatch.setattr(logcat_stream_guard.time, "monotonic", lambda: 500)

    def should_not_spawn(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invalid guard spawned fixture")

    monkeypatch.setattr(logcat_stream_guard.subprocess, "Popen", should_not_spawn)
    assert logcat_stream_guard.main(arguments) == 125


@pytest.mark.parametrize("mismatch", ["group", "parent"])
def test_guard_requires_own_new_process_group_and_exact_parent(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    monkeypatch.setattr(logcat_stream_guard.time, "monotonic", lambda: 500)
    monkeypatch.setattr(logcat_stream_guard.os, "getpid", lambda: 100)
    monkeypatch.setattr(
        logcat_stream_guard.os, "getpgrp", lambda: 99 if mismatch == "group" else 100
    )
    monkeypatch.setattr(
        logcat_stream_guard.os, "getppid", lambda: 99 if mismatch == "parent" else 45
    )
    assert logcat_stream_guard.main(["/absolute/safe.py", "45", "501"]) == 125


def test_guard_forwards_exact_fixture_fixed_arguments_and_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_pid = os.getpid()
    monkeypatch.setattr(logcat_stream_guard.os, "getpgrp", lambda: original_pid)
    monkeypatch.setattr(logcat_stream_guard.os, "getppid", lambda: 333)
    monkeypatch.setattr(logcat_stream_guard.time, "monotonic", lambda: 500)
    calls: list[Any] = []

    class Child:
        def poll(self) -> int:
            return 23

    def spawn(*args: Any, **kwargs: Any) -> Child:
        calls.append((args, kwargs))
        return Child()

    monkeypatch.setattr(logcat_stream_guard.subprocess, "Popen", spawn)
    script = tmp_path / "trusted-fixture.py"
    assert logcat_stream_guard.main([str(script), "333", "502"]) == 23
    assert len(calls) == 1
    assert calls[0][0][0] == [
        sys.executable,
        str(script),
        "--mcp-synthetic-logcat-v1",
    ]
    assert calls[0][1]["start_new_session"] is False
    assert calls[0][1]["stdout"] is None


@pytest.mark.parametrize("reason", ["parent_killed", "deadline"])
def test_guard_watchdog_kills_own_group_when_parent_dies_or_time_expires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    class Child:
        def poll(self) -> None:
            return None

    monkeypatch.setattr(logcat_stream_guard.subprocess, "Popen", lambda *a, **k: Child())
    monkeypatch.setattr(logcat_stream_guard.os, "getpgrp", lambda: os.getpid())
    monkeypatch.setattr(logcat_stream_guard.time, "sleep", lambda _: None)
    count = [0]

    def parent() -> int:
        count[0] += 1
        return 333 if count[0] == 1 or reason == "deadline" else 1

    monkeypatch.setattr(logcat_stream_guard.os, "getppid", parent)
    moments = iter([500.0, 504.0]) if reason == "deadline" else iter([500.0, 500.1])
    monkeypatch.setattr(logcat_stream_guard.time, "monotonic", lambda: next(moments))

    def die() -> None:
        raise RuntimeError("watchdog killed fixture group")

    monkeypatch.setattr(logcat_stream_guard, "_kill_own_group", die)
    with pytest.raises(RuntimeError, match="watchdog killed"):
        logcat_stream_guard.main([str(tmp_path / "fake.py"), "333", "503"])


@pytest.mark.parametrize("group_leader", [False, True])
def test_kill_guard_cannot_kill_unowned_process_group(
    monkeypatch: pytest.MonkeyPatch,
    group_leader: bool,
) -> None:
    actual_pid = os.getpid()
    monkeypatch.setattr(
        logcat_stream_guard.os, "getpgrp", lambda: actual_pid if group_leader else 22
    )
    killed: list[tuple[int, int]] = []

    def kill(group: int, sig: int) -> None:
        killed.append((group, sig))
        raise ProcessLookupError("test group already exited")

    monkeypatch.setattr(logcat_stream_guard.os, "killpg", kill)

    def fake_exit(code: int) -> None:
        raise SystemExit(code)

    monkeypatch.setattr(logcat_stream_guard.os, "_exit", fake_exit)
    with pytest.raises(SystemExit) as error:
        logcat_stream_guard._kill_own_group()
    assert error.value.code == 124
    assert killed == ([(actual_pid, signal.SIGKILL)] if group_leader else [])


def test_real_parent_sigkill_causes_guard_to_terminate_fixture_and_descendants(
    tmp_path: Path,
) -> None:
    status = tmp_path / "fixture-heartbeat.json"
    fake = tmp_path / "private-test-only-fixture.py"
    fake.write_text(
        "import json,os,time\nfrom pathlib import Path\n"
        f"p=Path({str(status)!r})\n"
        "while True:\n"
        "    temp=p.with_name(p.name+'.pending')\n"
        "    temp.write_text(json.dumps({'pid':os.getpid(),"
        "'pgid':os.getpgrp(),'beat':time.monotonic_ns()}))\n"
        "    os.replace(temp,p)\n"
        "    time.sleep(0.03)\n",
        encoding="utf-8",
    )
    parent_script = (
        "import sys,threading\nfrom pathlib import Path\n"
        "from android_mcp_host.logcat_stream_child import SyntheticLogcatProcessReader\n"
        "reader=SyntheticLogcatProcessReader(Path(sys.executable),Path(sys.argv[1]))\n"
        "reader('fake-avd','fake-handle','job_'+'x'*32,128,65536,3.0,threading.Event())\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_script, str(fake)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    fixture_pid = 0
    fixture_group = 0
    try:
        deadline = time.monotonic() + 1.75
        while not status.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert status.exists(), "synthetic fixture never reached guarded child"
        info = json.loads(status.read_text())
        fixture_pid = info["pid"]
        fixture_group = info["pgid"]
        assert fixture_pid != fixture_group, "watchdog must lead the separate process group"
        assert fixture_group != os.getpgrp(), "fixture must never share the pytest process group"
        # Emulate SIGKILL: Python finally code will NOT run in the Host process.
        parent.kill()
        parent.wait(timeout=2)
        stopped = False
        for _ in range(30):
            before = status.read_text()
            time.sleep(0.04)
            after = status.read_text()
            if before == after:
                # Stable heartbeat twice, rather than relying on zombie PID reaping.
                time.sleep(0.08)
                if status.read_text() == after:
                    stopped = True
                    break
        assert stopped, "orphaned fixture continued after its Host was SIGKILLed"
        assert time.monotonic() < deadline + 1.5
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        if fixture_group > 0 and fixture_group != os.getpgrp():
            try:
                os.killpg(fixture_group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_guard_yields_without_busy_loop_until_fixture_process_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = os.getpid()
    monkeypatch.setattr(logcat_stream_guard.os, "getpgrp", lambda: pid)
    monkeypatch.setattr(logcat_stream_guard.os, "getppid", lambda: 333)
    monkeypatch.setattr(logcat_stream_guard.time, "monotonic", lambda: 500)
    polls = [0]

    class Child:
        def poll(self) -> int | None:
            polls[0] += 1
            return 0 if polls[0] == 2 else None

    monkeypatch.setattr(logcat_stream_guard.subprocess, "Popen", lambda *a, **k: Child())
    sleeps: list[float] = []
    monkeypatch.setattr(logcat_stream_guard.time, "sleep", lambda seconds: sleeps.append(seconds))
    assert logcat_stream_guard.main([str(tmp_path / "trusted.py"), "333", "501"]) == 0
    assert polls == [2] and sleeps == [0.02]


def test_guard_executable_main_path_requires_valid_fixed_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runpy

    monkeypatch.setattr(sys, "argv", ["internal-guard.py"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(logcat_stream_guard.__file__)), run_name="__main__")
    assert result.value.code == 125

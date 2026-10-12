"""Real-process bounded capture on POSIX; no Android hardware is involved."""

import subprocess
import sys

import pytest

from android_mcp_host.command_runner import bounded_run


def test_reads_both_stdout_stderr_and_exit_status():
    p = bounded_run(
        [sys.executable, "-c", "import sys; print('hello'); print('warning', file=sys.stderr)"],
        3,
        4096,
    )
    assert p.returncode == 0
    assert p.stdout == "hello\n"
    assert p.stderr == "warning\n"
    assert not p.truncated


def test_capture_remains_bounded_if_child_generates_many_bytes():
    p = bounded_run([sys.executable, "-c", "print('X' * 200000)"], 3, 4096)
    assert p.truncated
    assert len(p.stdout.encode()) + len(p.stderr.encode()) <= 4096
    assert p.returncode != 0


def test_timeout_kills_child_and_does_not_return_success():
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_run([sys.executable, "-c", "import time; time.sleep(6)"], 0.15, 4096)


@pytest.mark.parametrize("seconds, limit", [(0, 1024), (500, 1024), (1, 100), (1, 999999)])
def test_bounded_runner_rejects_invalid_resource_limits(seconds, limit):
    with pytest.raises(ValueError):
        bounded_run([sys.executable, "-c", "print(1)"], seconds, limit)


def test_runner_never_injects_argv_into_a_shell():
    token = "hmm; echo SECOND"
    p = bounded_run([sys.executable, "-c", "import sys; print(sys.argv[1])", token], 3, 4096)
    assert p.stdout.strip() == token
    assert not p.truncated


def test_finished_process_does_not_need_to_be_killed():
    import android_mcp_host.command_runner as runner

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=3)
    runner._end_process(proc)


def test_killpg_process_lookup_race_is_handled(monkeypatch):
    import android_mcp_host.command_runner as runner

    class AlreadyDisappearing:
        pid = 1234

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    def vanished(*args):
        raise ProcessLookupError()

    monkeypatch.setattr(runner.os, "killpg", vanished)
    runner._end_process(AlreadyDisappearing())


def test_pipe_interrupted_by_nonblocking_read_retries(monkeypatch):
    import android_mcp_host.command_runner as runner

    real_read = runner.os.read
    seen = [False]

    def sometimes_block(fd, count):
        if count == 8192 and not seen[0]:
            seen[0] = True
            raise BlockingIOError()
        return real_read(fd, count)

    monkeypatch.setattr(runner.os, "read", sometimes_block)
    result = runner.bounded_run([sys.executable, "-c", "print('resumed')"], 3, 4096)
    assert result.stdout == "resumed\n"
    assert seen[0]


def test_cleanup_kills_process_group_even_if_launcher_has_exited(monkeypatch):
    import android_mcp_host.command_runner as runner

    calls = []

    class ParentExitedWithLiveDescendant:
        pid = 123456

        def poll(self):
            return 0

        def wait(self, timeout):
            calls.append(("wait", timeout))
            return 0

    def record_kill(pgid, sig):
        calls.append(("killpg", pgid, sig))

    monkeypatch.setattr(runner.os, "killpg", record_kill)
    runner._end_process(ParentExitedWithLiveDescendant())
    assert calls[0] == ("killpg", 123456, runner.signal.SIGKILL)
    assert calls[1] == ("wait", 2.0)

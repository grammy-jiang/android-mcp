"""H3.c bounded fake-only subprocess verification, timeout and group teardown."""

from __future__ import annotations

import hashlib
import signal
import subprocess
from pathlib import Path

import pytest
from test_avd_provisioning import NAME
from test_emulator_lifecycle_jobs import fake_emulator

import android_mcp_host.synthetic_emulator_backend as backend_module
from android_mcp_host.synthetic_emulator_backend import (
    SyntheticEmulatorBackend,
    SyntheticEmulatorError,
)


def fixture_script(path: Path, body: str) -> SyntheticEmulatorBackend:
    executable = path / "mcp-fixture-emulator"
    source = (
        "#!/usr/bin/env python3\n"
        "# ANDROID-MCP-SYNTHETIC-EMULATOR-ONLY\n"
        "import json, sys, time, os\n" + body
    )
    executable.write_text(source, encoding="utf-8")
    executable.chmod(0o700)
    return SyntheticEmulatorBackend(executable, hashlib.sha256(source.encode("utf-8")).hexdigest())


def test_missing_executable_cannot_be_used_as_real_qemu(tmp_path: Path) -> None:
    binary = tmp_path / "mcp-fixture-emulator"
    backend = SyntheticEmulatorBackend(binary, "a" * 64)
    assert backend._verify_executable() is False
    with pytest.raises(SyntheticEmulatorError, match="UNTRUSTED_FIXTURE"):
        backend.launch(NAME, tmp_path, 1.0)


def test_executable_content_read_error_refuses_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file, sha = fake_emulator(tmp_path)
    backend = SyntheticEmulatorBackend(file, sha)
    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "read_bytes",
            lambda path: (_ for _ in ()).throw(OSError("read unavailable")),
        )
        assert backend._verify_executable() is False


def test_spawn_oserror_generic_not_private_host_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file, sha = fake_emulator(tmp_path)
    backend = SyntheticEmulatorBackend(file, sha)
    with monkeypatch.context() as patch:
        patch.setattr(
            backend_module.subprocess,
            "Popen",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("sensitive path")),
        )
        with pytest.raises(SyntheticEmulatorError, match="SPAWN_FAILED"):
            backend.launch(NAME, tmp_path, 1.0)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("print('this-is-not-json', flush=True)\n", "READINESS_REJECTED"),
        ("print('[]', flush=True)\n", "READINESS_REJECTED"),
        ("print('x' * 5000, flush=True)\n", "READINESS_LIMIT"),
        ("sys.stdout.flush(); sys.exit(0)\n", "PROCESS_EXITED"),
        ("time.sleep(1.0)\n", "READINESS_TIMEOUT"),
    ],
)
def test_no_malformed_stdout_can_be_called_ready(
    tmp_path: Path,
    body: str,
    code: str,
) -> None:
    backend = fixture_script(tmp_path, body)
    with pytest.raises(SyntheticEmulatorError) as exc:
        backend.launch(NAME, tmp_path, 0.2 if code == "READINESS_TIMEOUT" else 2.0)
    assert exc.value.code == code


def test_multiple_json_lines_are_bounded_and_produce_only_one_report(
    tmp_path: Path,
) -> None:
    body = (
        'print(\'{"qemu":true,"avd":"mcp_fixture_api36","api":36,'
        '"abi":"arm64-v8a","boot_completed":true,'
        '"serial":"emulator-5554","pid":1}\', flush=True)\n'
        "print('not a second authority', flush=True)\n"
        "time.sleep(2.0)\n"
    )
    backend = fixture_script(tmp_path, body)
    process, record = backend.launch(NAME, tmp_path, 1.0)
    try:
        assert record["avd"] == NAME
        assert record["pid"] == 1
        assert process.poll() is None
    finally:
        assert backend.stop(process)


class FakePipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, *, wait_failures: int = 0, running: bool = True) -> None:
        self.pid = 873421
        self.stdin = FakePipe()
        self.stdout = FakePipe()
        self.wait_failures = wait_failures
        self.waits = 0
        self.running = running

    def poll(self) -> int | None:
        return None if self.running else 0

    def wait(self, timeout: float) -> int:
        self.waits += 1
        if self.waits <= self.wait_failures:
            raise subprocess.TimeoutExpired(["synthetic-fixture"], timeout)
        self.running = False
        return 0


def test_forced_stop_escalates_within_its_own_group_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = FakeProcess(wait_failures=1)
    calls: list[tuple[int, signal.Signals]] = []
    with monkeypatch.context() as patch:
        patch.setattr(backend_module.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
        assert SyntheticEmulatorBackend.stop(child) is True  # type: ignore[arg-type]
    assert calls == [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)]
    assert child.stdin.closed and child.stdout.closed


def test_double_timeout_reports_uncertain_and_releases_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = FakeProcess(wait_failures=2)
    signals: list[int] = []
    with monkeypatch.context() as patch:
        patch.setattr(backend_module.os, "killpg", lambda pid, sig: signals.append(sig))
        assert SyntheticEmulatorBackend.stop(child) is False  # type: ignore[arg-type]
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert child.stdin.closed and child.stdout.closed


def test_killpg_process_no_longer_exists_is_never_treated_as_pid_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = FakeProcess(wait_failures=1)
    calls: list[int] = []

    def signal_group(pid: int, sig: int) -> None:
        calls.append(sig)
        if sig == signal.SIGKILL:
            raise ProcessLookupError()

    with monkeypatch.context() as patch:
        patch.setattr(backend_module.os, "killpg", signal_group)
        assert SyntheticEmulatorBackend.stop(child) is True  # type: ignore[arg-type]
    assert calls == [signal.SIGTERM, signal.SIGKILL]
    assert child.stdin.closed and child.stdout.closed


def test_oserror_while_stopping_process_cannot_be_reported_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = FakeProcess()
    with monkeypatch.context() as patch:
        patch.setattr(
            backend_module.os,
            "killpg",
            lambda *args: (_ for _ in ()).throw(OSError("no permission")),
        )
        assert SyntheticEmulatorBackend.stop(child) is False  # type: ignore[arg-type]
    assert child.stdin.closed and child.stdout.closed


def test_already_exited_child_requires_no_process_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = FakeProcess(running=False)
    with monkeypatch.context() as patch:
        patch.setattr(
            backend_module.os,
            "killpg",
            lambda *args: (_ for _ in ()).throw(AssertionError("unexpected PID signal")),
        )
        assert SyntheticEmulatorBackend.stop(child) is True  # type: ignore[arg-type]
    assert child.stdin.closed and child.stdout.closed


def test_parent_exit_between_readiness_and_return_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable, digest = fake_emulator(tmp_path)
    backend = SyntheticEmulatorBackend(executable, digest)
    fake = FakeProcess(running=False)
    with monkeypatch.context() as patch:
        patch.setattr(backend_module.subprocess, "Popen", lambda *args, **kwargs: fake)
        patch.setattr(backend, "_read_ready", lambda child, budget: {"qemu": True})
        with pytest.raises(SyntheticEmulatorError, match="PROCESS_EXITED"):
            backend.launch(NAME, tmp_path, 0.5)
    assert fake.stdin.closed and fake.stdout.closed


def test_fake_process_self_terminates_when_parent_stdin_closes(tmp_path: Path) -> None:
    executable, digest = fake_emulator(tmp_path)
    backend = SyntheticEmulatorBackend(executable, digest)
    child, report = backend.launch(NAME, tmp_path, 2.0)
    assert report["pid"] == child.pid
    assert child.stdin is not None
    child.stdin.close()
    try:
        child.wait(timeout=2)
    finally:
        if child.poll() is None:
            backend.stop(child)
        elif child.stdout is not None:
            child.stdout.close()
    assert child.poll() is not None


def test_symlinked_parent_with_correct_basename_still_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real-fixture-directory"
    real.mkdir()
    executable, digest = fake_emulator(real)
    alias = tmp_path / "symlinked-fixture-directory"
    alias.symlink_to(real, target_is_directory=True)
    linked_path = alias / "mcp-fixture-emulator"
    assert linked_path.name == executable.name
    controller = SyntheticEmulatorBackend(linked_path, digest)
    assert controller._verify_executable() is False
    with pytest.raises(SyntheticEmulatorError, match="UNTRUSTED_FIXTURE"):
        controller.launch(NAME, tmp_path, 0.5)


def test_fake_subprocess_without_pipes_does_not_break_cleanup() -> None:
    child = FakeProcess(running=False)
    child.stdin = None
    child.stdout = None
    assert SyntheticEmulatorBackend.stop(child) is True  # type: ignore[arg-type]
    assert child.waits == 1

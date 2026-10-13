"""H3.e serializes each disposable test target across threads and processes."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_instrumentation_jobs import (
    COMPONENT,
    RUN_REQUEST,
    setup_fixture,
    success,
)

from android_mcp_host.command_runner import RunResult
from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock


def test_lock_is_private_nonblocking_and_target_scoped(tmp_path: Path) -> None:
    root = tmp_path / "private-root"
    root.mkdir(mode=0o700)
    first = "mcpavd_" + "a" * 32
    second = "mcpavd_" + "b" * 32
    fd = claim_fixture_lock(root, first)
    assert isinstance(fd, int)
    try:
        assert claim_fixture_lock(root, first) is None
        other = claim_fixture_lock(root, second)
        assert isinstance(other, int)
        os.close(other)
    finally:
        os.close(fd)
    lock = next(root.glob("fixture-instrumentation-*.lock"))
    assert lock.stat().st_mode & 0o777 == 0o600


def test_lock_across_independent_processes_cannot_acquire_occupied_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-root"
    root.mkdir(mode=0o700)
    handle = "mcpavd_" + "c" * 32
    fd = claim_fixture_lock(root, handle)
    assert fd is not None
    program = (
        "import sys,os\n"
        "from pathlib import Path\n"
        "from android_mcp_host.emulator_instrumentation_support import claim_fixture_lock\n"
        "fd=claim_fixture_lock(Path(sys.argv[1]),sys.argv[2])\n"
        "print('BUSY' if fd is None else 'UNSAFE_DOUBLE_CLAIM')\n"
        "if fd is not None: os.close(fd)\n"
    )
    try:
        child = subprocess.run(
            [sys.executable, "-c", program, str(root), handle],
            timeout=10,
            capture_output=True,
            text=True,
            check=False,
        )
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "BUSY"
    finally:
        os.close(fd)


def test_lock_does_not_adopt_insecure_symlink_or_hardlink(tmp_path: Path) -> None:
    root = tmp_path / "private-root"
    root.mkdir(mode=0o700)
    handle = "mcpavd_" + "d" * 32
    fd = claim_fixture_lock(root, handle)
    assert fd is not None
    os.close(fd)
    lock = next(root.glob("fixture-instrumentation-*.lock"))
    lock.chmod(0o644)
    with pytest.raises(OSError):
        claim_fixture_lock(root, handle)
    lock.chmod(0o600)
    hardlink = tmp_path / "link"
    os.link(lock, hardlink)
    with pytest.raises(OSError):
        claim_fixture_lock(root, handle)
    hardlink.unlink()
    lock.unlink()
    lock.symlink_to(tmp_path / "foreign-host-path")
    with pytest.raises(OSError):
        claim_fixture_lock(root, handle)


def test_concurrent_requests_for_one_avd_cannot_run_simultaneously(tmp_path: Path) -> None:
    entered = Event()
    release = Event()
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        entered.set()
        assert release.wait(8)
        return success(*args)

    task, live, ledger, artifacts, avd, lid, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            task.submit,
            "run",
            NAME,
            avd,
            lid,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        try:
            assert entered.wait(4)
            independent = task.submit(
                "run",
                NAME,
                avd,
                lid,
                apk,
                sha,
                COMPONENT,
                request_id="independent-fixture-test",
            )
            assert independent["status"] == "blocked"
            assert independent["errors"][0]["code"] == "RECOVERY_REQUIRED"
            assert calls == [1]
            assert len(ledger.list_status(OWNER)) == 2
        finally:
            release.set()
        assert first.result(timeout=15)["status"] == "ok"
    live.shutdown()


def test_unsafe_lock_blocks_execution_and_preserves_existing_jobs(tmp_path: Path) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        return success(*args)

    task, live, ledger, artifacts, avd, lid, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    try:
        private = ledger.private_root
        digest = hashlib.sha256(avd.encode("ascii")).hexdigest()[:32]
        unsafe = private / ("fixture-instrumentation-" + digest + ".lock")
        unsafe.write_bytes(b"not private")
        unsafe.chmod(0o644)
        blocked = task.submit(
            "run",
            NAME,
            avd,
            lid,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert blocked["status"] == "blocked"
        assert blocked["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert calls == [0]
        assert len(ledger.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_replay_includes_full_target_provenance_without_new_execution(tmp_path: Path) -> None:
    executions = [0]

    def runner(*args: Any) -> RunResult:
        executions[0] += 1
        return success(*args)

    task, live, ledger, artifacts, avd, lid, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    try:
        original = task.submit(
            "run",
            NAME,
            avd,
            lid,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        replay = task.submit(
            "run",
            NAME,
            avd,
            lid,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert replay["status"] == "ok"
        assert replay["avd_name"] == NAME
        assert replay["avd_handle"] == avd
        assert replay["apk_sha256"] == sha
        assert replay["report_handle"] == original["report_handle"]
        assert executions == [1]
    finally:
        live.shutdown()

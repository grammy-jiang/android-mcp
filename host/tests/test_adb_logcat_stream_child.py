"""H5.b bounded trusted fake Python reader, subprocess group cleanup and leases."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from test_adb_logcat_stream_jobs import NAME, OWNER, RAW, REQ, builder, run

from android_mcp_host.logcat_stream_child import SyntheticLogcatProcessReader
from android_mcp_host.logcat_stream_store import LogcatStreamStore, StreamStoreError


def script(tmp_path: Path, body: str) -> Path:
    source = tmp_path / "synthetic-logcat-fixture.py"
    source.write_text(body, encoding="utf-8")
    return source


def test_fixture_process_reads_finite_marker_and_integrates_with_stream(tmp_path: Path) -> None:
    file = script(tmp_path, f"import sys\nsys.stdout.buffer.write({RAW!r})\n")
    reader = SyntheticLogcatProcessReader(Path(sys.executable), file)
    worker, live, jobs, handle, lid, calls = builder(tmp_path, fixture=reader)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "ok"
        page = run(
            worker, handle, lid, "poll", job_id=response["job_id"], cursor=response["cursor"]
        )
        assert page["status"] == "ended"
        assert "[REDACTED]" in [x["message"] for x in page["entries"]]
        assert b"private-secret" not in worker._streams._index.read_bytes()
    finally:
        live.shutdown()


def test_fake_process_timeout_kills_isolated_group(tmp_path: Path) -> None:
    pid = tmp_path / "child-pid"
    file = script(
        tmp_path,
        "from pathlib import Path\nimport os,time\n"
        f"Path({str(pid)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
    )
    reader = SyntheticLogcatProcessReader(Path(sys.executable), file)
    with pytest.raises(subprocess.TimeoutExpired):
        reader(NAME, "fake-avd", "job_" + "x" * 32, 128, 65536, 0.25, threading.Event())
    assert pid.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)


def test_fixture_process_stop_cancels_and_kills_group(tmp_path: Path) -> None:
    pid = tmp_path / "child-pid"
    file = script(
        tmp_path,
        "from pathlib import Path\nimport os,time\n"
        f"Path({str(pid)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
    )
    reader = SyntheticLogcatProcessReader(Path(sys.executable), file)
    stop = threading.Event()
    errors: list[BaseException] = []

    def target() -> None:
        try:
            reader(NAME, "fake-avd", "job_" + "x" * 32, 128, 65536, 2.0, stop)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=target)
    thread.start()
    deadline = time.monotonic() + 1
    while not pid.exists() and time.monotonic() < deadline:
        time.sleep(0.015)
    assert pid.exists()
    stop.set()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], InterruptedError)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)


def test_fixture_output_size_limit_kills_child_without_private_storage(tmp_path: Path) -> None:
    file = script(tmp_path, "import os\nos.write(1,b'Z'*65537)\n")
    reader = SyntheticLogcatProcessReader(Path(sys.executable), file)
    with pytest.raises(ValueError, match="output cap"):
        reader(NAME, "fake-avd", "job_" + "x" * 32, 128, 65536, 1.0, threading.Event())


@pytest.mark.parametrize(
    "body",
    [
        "import sys\nsys.exit(3)\n",
        "raise RuntimeError('synthetic failure')\n",
    ],
)
def test_fixture_nonzero_exit_is_never_success(tmp_path: Path, body: str) -> None:
    reader = SyntheticLogcatProcessReader(Path(sys.executable), script(tmp_path, body))
    with pytest.raises(RuntimeError, match="unsuccessful"):
        reader(NAME, "fake-avd", "job_" + "x" * 32, 128, 65536, 1.0, threading.Event())


@pytest.mark.parametrize(
    "bad",
    [
        {"maximum": 0},
        {"maximum": 129},
        {"max_bytes": 0},
        {"max_bytes": 65537},
        {"timeout": -1},
        {"timeout": 3.01},
    ],
)
def test_reader_invalid_limits_rejected_before_spawn(tmp_path: Path, bad: dict[str, Any]) -> None:
    reader = SyntheticLogcatProcessReader(
        Path(sys.executable),
        script(tmp_path, "raise AssertionError('invoked')\n"),
    )
    args: dict[str, Any] = {
        "name": NAME,
        "handle": "fake-avd",
        "lifecycle": "job_" + "x" * 32,
        "maximum": 128,
        "max_bytes": 65536,
        "timeout": 1.0,
        "stop": threading.Event(),
    }
    args.update(bad)
    with pytest.raises(ValueError, match="limits"):
        reader(**args)


def test_reader_rejects_relative_symlink_and_writable_fixture(tmp_path: Path) -> None:
    executable = Path(sys.executable)
    file = script(tmp_path, "print('safe')\n")
    with pytest.raises(ValueError):
        SyntheticLogcatProcessReader(executable, Path("relative.py"))
    link = tmp_path / "shortcut.py"
    link.symlink_to(file)
    with pytest.raises(ValueError):
        SyntheticLogcatProcessReader(executable, link)
    file.chmod(0o666)
    with pytest.raises(ValueError):
        SyntheticLogcatProcessReader(executable, file)


def test_store_signed_cursor_lease_expires_and_blocks_stale_session(tmp_path: Path) -> None:
    clock = [500.0]
    root = tmp_path / "private-job-root"
    owner, handle, lid, request = OWNER, "fake-avd", "job_" + "x" * 32, REQ
    jid = "job_" + "y" * 32
    store = LogcatStreamStore(root, clock=lambda: clock[0])
    event = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    start = store.insert(jid, owner, handle, lid, request, event, 0, False, 1)
    assert start["cursor"].startswith("cur_000_")
    clock[0] = 502.0
    with pytest.raises(StreamStoreError) as error:
        store.poll(jid, owner, handle, lid, request, start["cursor"], 1)
    assert error.value.code == "EXPIRED"
    with pytest.raises(StreamStoreError):
        store.peek(jid, owner, handle, lid, request)


def test_store_wrong_owner_request_and_signature_fail(tmp_path: Path) -> None:
    root = tmp_path / "owner-private"
    store = LogcatStreamStore(root)
    jid, lid = "job_" + "x" * 32, "job_" + "y" * 32
    start = store.insert(
        jid,
        OWNER,
        "avd-fake",
        lid,
        REQ,
        [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}],
        0,
        False,
        120,
    )
    for owner, handle, life, req in [
        ("other-owner", "avd-fake", lid, REQ),
        (OWNER, "wrong-avd", lid, REQ),
        (OWNER, "avd-fake", "job_" + "z" * 32, REQ),
        (OWNER, "avd-fake", lid, "other-request"),
    ]:
        with pytest.raises(StreamStoreError) as error:
            store.poll(jid, owner, handle, life, req, start["cursor"], 1)
        assert error.value.code == "NOT_FOUND"
    tampered = start["cursor"][:-1] + ("b" if start["cursor"][-1] != "b" else "c")
    with pytest.raises(StreamStoreError) as error:
        store.poll(jid, OWNER, "avd-fake", lid, REQ, tampered, 1)
    assert error.value.code == "CURSOR_CONFLICT"
    got = store.poll(jid, OWNER, "avd-fake", lid, REQ, start["cursor"], 1)
    assert got["state"] == "ended"


def test_store_private_index_symlink_and_wrong_permission_rejected(tmp_path: Path) -> None:
    root = tmp_path / "private"
    store = LogcatStreamStore(root)
    index = store._index
    index.chmod(0o644)
    with pytest.raises(StreamStoreError):
        store.peek("job_" + "x" * 32, OWNER, "avd-fake", "job_" + "y" * 32, REQ)
    index.chmod(0o600)
    index.rename(root / "previous.db")
    index.symlink_to(root / "previous.db")
    with pytest.raises(StreamStoreError):
        store.peek("job_" + "x" * 32, OWNER, "avd-fake", "job_" + "y" * 32, REQ)


def test_store_full_quota_does_not_evict_live_session(tmp_path: Path) -> None:
    store = LogcatStreamStore(tmp_path / "private")
    event = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    for number in range(32):
        store.insert(
            f"job_{number:032d}",
            OWNER,
            "fake-avd",
            "job_" + "x" * 32,
            f"request-{number}",
            event,
            0,
            False,
            120,
        )
    with pytest.raises(StreamStoreError) as error:
        store.insert(
            "job_" + "z" * 32,
            OWNER,
            "fake-avd",
            "job_" + "x" * 32,
            "request-33",
            event,
            0,
            False,
            120,
        )
    assert error.value.code == "JOB_UNAVAILABLE"
    first = store.peek("job_" + f"{0:032d}", OWNER, "fake-avd", "job_" + "x" * 32, "request-0")
    assert first["cursor"].startswith("cur_000_")


def test_store_stop_revokes_remaining_events_and_can_be_repeated(tmp_path: Path) -> None:
    store = LogcatStreamStore(tmp_path / "private")
    jid, lid = "job_" + "x" * 32, "job_" + "y" * 32
    start = store.insert(
        jid,
        OWNER,
        "fake-avd",
        lid,
        REQ,
        [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}],
        0,
        False,
        60,
    )
    assert store.stop(jid, OWNER, "fake-avd", lid, REQ) == "stopped"
    assert store.stop(jid, OWNER, "fake-avd", lid, REQ) == "stopped"
    with pytest.raises(StreamStoreError) as error:
        store.poll(jid, OWNER, "fake-avd", lid, REQ, start["cursor"], 1)
    assert error.value.code == "STOPPED"


def test_actual_service_stop_interrupts_child_process_without_orphan(tmp_path: Path) -> None:
    pid = tmp_path / "real-child-pid"
    fake = script(
        tmp_path,
        "from pathlib import Path\nimport os,time\n"
        f"Path({str(pid)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
    )
    reader = SyntheticLogcatProcessReader(Path(sys.executable), fake)
    worker, live, jobs, handle, lid, calls = builder(tmp_path, fixture=reader)
    responses: list[dict[str, Any]] = []
    thread = threading.Thread(target=lambda: responses.append(run(worker, handle, lid, "start")))
    try:
        thread.start()
        deadline = time.monotonic() + 1.5
        while not pid.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pid.exists()
        current = [r for r in jobs.list_status(OWNER) if r["job_id"] != lid]
        assert len(current) == 1
        cancelled = run(worker, handle, lid, "stop", job_id=current[0]["job_id"])
        assert cancelled["status"] == "uncertain"
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert responses[0]["status"] == "uncertain"
        assert responses[0]["errors"][0]["code"] == "CANCELLED"
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid.read_text()), 0)
    finally:
        live.shutdown()

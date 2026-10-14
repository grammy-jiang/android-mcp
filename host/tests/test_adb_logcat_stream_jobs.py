"""H5.b T-H5B-01..06: finite synthetic Logcat, single-use cursors and denial."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as START_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.server import create_server
from android_mcp_host.synthetic_logcat_stream import (
    StreamApproval,
    StreamFrame,
    SyntheticLogcatStream,
    get_logcat_stream_schema,
)

REQ = "synthetic-logcat-req-001"
RAW_SECRETS = "authorization=Bearer.secret-user@example.com"
ARTIFICIAL_TIME = 1781650500.0


def line(text: str, *, tag: str = "McpTest", priority: str = "I") -> bytes:
    return f"10-14 14:03:01.111  100  100 {priority} {tag}: {text}\n".encode()


RAW = b"".join(
    [
        line("STATE=ready"),
        line("EVENT=connected"),
        line("TOKEN=private-secret"),
        line("UPTIME_SECONDS=120"),
        line("BATTERY_PERCENT=61"),
        line("STATE=idle"),
    ]
)


def builder(
    tmp_path: Path,
    *,
    active: bool = True,
    approved: bool = True,
    data: bytes = RAW,
    fixture: Any = None,
    clock: Any = time.time,
) -> tuple[SyntheticLogcatStream, Any, Any, str, str, list[Any]]:
    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        result = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert result["status"] == "ok"
        lid = result["job_id"]
    grant = (
        StreamApproval(
            owner=OWNER,
            avd_handle=handle,
            lifecycle_job_id=lid,
            purpose="synthetic-sanitized-logcat",
            valid_until_epoch=clock() + 115,
            ttl_s=60,
        )
        if approved
        else None
    )
    calls: list[Any] = []
    if fixture is None:

        def fixture(
            name: str,
            found_handle: str,
            found_lid: str,
            max_events: int,
            byte_cap: int,
            deadline_s: float,
            stop: threading.Event,
        ) -> StreamFrame:
            calls.append((name, found_handle, found_lid, max_events, byte_cap, deadline_s))
            assert not stop.is_set()
            return StreamFrame(data, name, found_handle, found_lid, True, True)

    worker = SyntheticLogcatStream(
        live.provisioner,
        live,
        jobs,
        owner=OWNER,
        approval=grant,
        fixture_read=fixture,
        clock=clock,
    )
    return worker, live, jobs, handle, lid, calls


def run(
    worker: SyntheticLogcatStream,
    handle: str,
    lid: str,
    action: str,
    *,
    request: str = REQ,
    **kwargs: Any,
) -> dict[str, Any]:
    return worker.submit(
        action,
        NAME,
        handle,
        lid,
        request_id=request,
        **kwargs,
    )


def check(data: dict[str, Any]) -> None:
    Draft202012Validator(get_logcat_stream_schema()).validate(data)


def test_t_h5b_01_finite_cursor_monotonic_pages_and_stop(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        start = run(worker, handle, lid, "start")
        check(start)
        assert start["status"] == "ok"
        assert start["stream_state"] == "ready"
        assert start["cursor"].startswith("cur_000_")
        assert start["total_events"] == 6
        assert start["truncated"] is False
        assert start["real_logcat_stream_enabled"] is False
        assert calls == [(NAME, handle, lid, 128, 65536, 3.0)]
        cursor = start["cursor"]
        positions: list[tuple[int, int]] = []
        messages: list[str] = []
        for _ in range(3):
            result = run(
                worker,
                handle,
                lid,
                "poll",
                job_id=start["job_id"],
                cursor=cursor,
                page_size=2,
            )
            check(result)
            assert result["status"] in ("ok", "ended")
            positions.append((result["from_index"], result["next_index"]))
            messages.extend(item["message"] for item in result["entries"])
            cursor = result["cursor"]
        assert positions == [(0, 2), (2, 4), (4, 6)]
        assert cursor is None
        assert messages == [
            "STATE=ready",
            "EVENT=connected",
            "[REDACTED]",
            "UPTIME_SECONDS=120",
            "BATTERY_PERCENT=61",
            "STATE=idle",
        ]
        assert run(worker, handle, lid, "stop", job_id=start["job_id"])["status"] == "ended"
        assert jobs.status(OWNER, start["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


def test_t_h5b_02_wrong_target_request_duplicate_cursor_and_restart(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        started = run(worker, handle, lid, "start")
        args = {"job_id": started["job_id"], "cursor": started["cursor"], "page_size": 2}
        assert run(worker, "USB-physical-target", lid, "poll", **args)["status"] == "blocked"
        assert (
            run(worker, handle, lid, "poll", request="different-request", **args)["status"]
            == "blocked"
        )
        assert run(worker, handle, "job_" + "r" * 32, "poll", **args)["status"] == "blocked"
        first = run(worker, handle, lid, "poll", **args)
        assert first["status"] == "ok"
        replay = run(worker, handle, lid, "poll", **args)
        assert replay["errors"][0]["code"] == "CURSOR_CONFLICT"
        assert replay["entries"] == []
        restored = SyntheticLogcatStream(
            live.provisioner,
            live,
            jobs,
            owner=OWNER,
            approval=worker._approval,
            fixture_read=worker._fixture,
        )
        again = run(restored, handle, lid, "start")
        assert again["job_id"] == started["job_id"]
        assert again["cursor"] == first["cursor"]
        assert len(calls) == 1
        page2 = run(
            restored,
            handle,
            lid,
            "poll",
            job_id=again["job_id"],
            cursor=again["cursor"],
            page_size=2,
        )
        assert page2["from_index"] == 2
        assert (
            run(
                worker,
                handle,
                lid,
                "poll",
                job_id=again["job_id"],
                cursor=first["cursor"],
                page_size=2,
            )["errors"][0]["code"]
            == "CURSOR_CONFLICT"
        )
    finally:
        live.shutdown()


@pytest.mark.parametrize("tag", ["*", "Unknown", "TOKEN", "McpTest:I", "", "McpTest\n"])
def test_t_h5b_03_unknown_tag_and_injection_denied_before_reader(tmp_path: Path, tag: str) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        response = run(worker, handle, lid, "start", tag=tag)
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == "INVALID_TAG"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "invalid",
    [
        b"\x00garbage",
        b"\xff\xfe",
        b"hello world\n",
        b"x" * 65537,
        b"10-14 14:03:01.111  100  100 I McpTest: STATE=ready\r\n",
    ],
)
def test_t_h5b_03_hostile_raw_frame_never_persists(tmp_path: Path, invalid: bytes) -> None:
    worker, live, jobs, handle, lid, _ = builder(tmp_path, data=invalid)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "failed"
        assert response["errors"][0]["code"] in ("INVALID_LOGCAT", "OUTPUT_LIMIT")
        assert response["entries"] == []
        assert worker._streams._index.exists()
        with worker._streams._connect() as db:
            assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0
    finally:
        live.shutdown()


def test_t_h5b_03_all_non_allowlisted_messages_are_redacted_before_sqlite(tmp_path: Path) -> None:
    raw = line(RAW_SECRETS) + line("STATE=ready", tag="System")
    worker, live, jobs, handle, lid, calls = builder(tmp_path, data=raw)
    try:
        start = run(worker, handle, lid, "start")
        assert start["status"] == "ok"
        payload = worker._streams._index.read_bytes()
        assert RAW_SECRETS.encode() not in payload
        assert b"Bearer" not in payload
        page = run(worker, handle, lid, "poll", job_id=start["job_id"], cursor=start["cursor"])
        assert page["status"] == "ended"
        assert [x["message"] for x in page["entries"]] == ["[REDACTED]", "STATE=ready"]
        assert RAW_SECRETS not in json.dumps(start) + json.dumps(page)
        assert start["raw_logcat_returned"] is False
    finally:
        live.shutdown()


def test_t_h5b_04_huge_finite_fixture_drops_excess_and_caps_pages(tmp_path: Path) -> None:
    raw = line("STATE=ready") * 300
    assert len(raw) < 65536
    worker, live, jobs, handle, lid, calls = builder(tmp_path, data=raw)
    try:
        start = run(worker, handle, lid, "start", max_events=5)
        assert start["status"] == "ok"
        assert start["total_events"] == 5
        assert start["dropped_events"] == 295
        assert start["truncated"] is True
        assert worker._streams._index.stat().st_size < 1024 * 1024
        cursor = start["cursor"]
        for k in range(3):
            result = run(
                worker,
                handle,
                lid,
                "poll",
                job_id=start["job_id"],
                cursor=cursor,
                page_size=2,
                max_events=5,
            )
            assert len(result["entries"]) == (2 if k < 2 else 1)
            assert result["truncated"] is True
            cursor = result["cursor"]
        assert cursor is None
    finally:
        live.shutdown()


def test_t_h5b_05_timeout_marks_uncertain_and_cleans_private_rows(tmp_path: Path) -> None:
    def fails(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fake-only-logcat"], 0.1)

    worker, live, jobs, handle, lid, calls = builder(tmp_path, fixture=fails)
    try:
        output = run(worker, handle, lid, "start")
        assert output["status"] == "uncertain"
        assert output["errors"][0]["code"] == "TIMEOUT"
        assert jobs.status(OWNER, output["job_id"])["job"]["state"] == "uncertain"
        with worker._streams._connect() as db:
            assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0
        assert run(worker, handle, lid, "start")["errors"][0]["code"] == "RECOVERY_REQUIRED"
    finally:
        live.shutdown()


def test_t_h5b_05_cooperative_stop_during_capture_prevents_success(tmp_path: Path) -> None:
    begun = threading.Event()
    finished = threading.Event()

    def slow(
        name: str,
        handle: str,
        lid: str,
        maximum: int,
        max_bytes: int,
        timeout: float,
        stopped: threading.Event,
    ) -> StreamFrame:
        begun.set()
        assert stopped.wait(1.5)
        finished.set()
        return StreamFrame(RAW, name, handle, lid, True, True)

    worker, live, jobs, handle, lid, calls = builder(tmp_path, fixture=slow)
    outcome: list[dict[str, Any]] = []
    try:
        thread = threading.Thread(target=lambda: outcome.append(run(worker, handle, lid, "start")))
        thread.start()
        assert begun.wait(1.5)
        active = [
            row
            for row in jobs.list_status(OWNER)
            if row["job_id"] != lid and row["state"] == "running"
        ]
        assert len(active) == 1
        stopped = run(worker, handle, lid, "stop", job_id=active[0]["job_id"])
        assert stopped["status"] == "uncertain"
        assert stopped["errors"][0]["code"] == "CANCELLED"
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert finished.is_set()
        assert outcome[0]["status"] == "uncertain"
        with worker._streams._connect() as db:
            assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0
    finally:
        live.shutdown()


def test_t_h5b_05_disconnect_after_fixture_invalidates_stream(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, _ = builder(tmp_path)

    def disconnect(*args: Any) -> StreamFrame:
        live.shutdown()
        return StreamFrame(RAW, NAME, handle, lid, True, True)

    worker._fixture = disconnect
    result = run(worker, handle, lid, "start")
    assert result["status"] == "uncertain"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"


def test_t_h5b_06_real_inprocess_mcp_typed_schema_and_denial(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)

    async def check_mcp() -> None:
        async with Client(create_server()) as minimal:
            originals = {x.name: x for x in await minimal.list_tools()}
        async with Client(create_server(logcat_stream_worker=worker)) as client:
            tools = {x.name: x for x in await client.list_tools()}
            assert set(tools) == {*originals, "host_logcat_stream"}
            assert all(tools[key] == value for key, value in originals.items())
            tool = tools["host_logcat_stream"]
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.output_schema == get_logcat_stream_schema()
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["destructiveHint"] is True
            assert hints["openWorldHint"] is False
            base = {"avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid}
            planned = await client.call_tool("host_logcat_stream", {"action": "plan", **base})
            assert planned.structured_content["status"] == "planned"
            received = await client.call_tool(
                "host_logcat_stream",
                {"action": "start", "request_id": REQ, **base},
            )
            assert not received.is_error
            start = received.structured_content
            check(start)
            assert start["status"] == "ok"
            poll = await client.call_tool(
                "host_logcat_stream",
                {
                    "action": "poll",
                    "request_id": REQ,
                    "job_id": start["job_id"],
                    "cursor": start["cursor"],
                    "page_size": 8,
                    **base,
                },
            )
            check(poll.structured_content)
            assert poll.structured_content["status"] == "ended"
            assert len(poll.structured_content["entries"]) == 6
            assert "private-secret" not in json.dumps(poll.structured_content)

    try:
        asyncio.run(check_mcp())
    finally:
        live.shutdown()

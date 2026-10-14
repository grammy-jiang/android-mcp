"""H5.b adversarial policy, consent expiry, stale state, persistence and tampering."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adb_logcat_stream_jobs import NAME, OWNER, RAW, REQ, builder, line, run

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.logcat_stream_store import LogcatStreamStore, StreamStoreError
from android_mcp_host.logcat_stream_support import (
    MAX_EVENTS,
    parse_events,
    valid_stored_events,
)
from android_mcp_host.synthetic_logcat_stream import (
    StreamFrame,
    SyntheticLogcatStream,
)


@pytest.mark.parametrize(
    ("action", "kwargs", "code"),
    [
        ("bad-action", {}, "INVALID_ACTION"),
        ("start", {"request_id": "x"}, "INVALID_INPUT"),
        ("start", {"page_size": 0}, "INVALID_INPUT"),
        ("start", {"page_size": 17}, "INVALID_INPUT"),
        ("start", {"page_size": True}, "INVALID_INPUT"),
        ("start", {"max_events": 0}, "INVALID_INPUT"),
        ("start", {"max_events": MAX_EVENTS + 1}, "INVALID_INPUT"),
        ("start", {"max_events": True}, "INVALID_INPUT"),
        ("start", {"ttl_s": 0}, "INVALID_INPUT"),
        ("start", {"ttl_s": 121}, "INVALID_INPUT"),
        ("start", {"ttl_s": True}, "INVALID_INPUT"),
        ("plan", {"cursor": "fake"}, "INVALID_INPUT"),
        ("start", {"job_id": "job_" + "x" * 32}, "INVALID_INPUT"),
        ("stop", {}, "INVALID_INPUT"),
        ("poll", {"job_id": "job_" + "x" * 32}, "INVALID_INPUT"),
        ("poll", {"cursor": "garbage", "job_id": ""}, "INVALID_INPUT"),
        ("start", {"tag": "Unknown"}, "INVALID_TAG"),
    ],
)
def test_invalid_arguments_are_denied_before_reader(
    tmp_path: Path,
    action: str,
    kwargs: dict[str, Any],
    code: str,
) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        request = kwargs.pop("request_id", REQ)
        response = run(worker, handle, lid, action, request=request, **kwargs)
        assert response["errors"][0]["code"] == code
        assert response["entries"] == []
        assert calls == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "changed",
    [
        {"owner": "other-owner"},
        {"avd_handle": "not-this-avd"},
        {"lifecycle_job_id": "job_" + "x" * 32},
        {"purpose": "not-a-logcat-purpose"},
        {"valid_until_epoch": float("nan")},
        {"valid_until_epoch": 0.0},
        {"ttl_s": 0},
        {"ttl_s": True},
    ],
)
def test_test_only_approval_must_match_exact_owner_lifecycle_and_lease(
    tmp_path: Path,
    changed: dict[str, Any],
) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        assert worker._approval is not None
        worker._approval = replace(worker._approval, **changed)
        response = run(worker, handle, lid, "start")
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert calls == []
    finally:
        live.shutdown()


def test_approval_non_numeric_clock_denied_and_mismatched_owner_constructor(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        worker._clock = lambda: object()
        assert run(worker, handle, lid, "start")["errors"][0]["code"] == "CONSENT_REQUIRED"
        with pytest.raises(ValueError, match="owner"):
            SyntheticLogcatStream(live.provisioner, live, jobs, owner="wrong")
    finally:
        live.shutdown()


def test_independent_approval_without_fixture_does_not_enable_real_logcat(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    worker._fixture = None
    try:
        assert run(worker, handle, lid, "start")["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "alter",
    [
        {"avd_name": "evil"},
        {"avd_handle": "wrong"},
        {"lifecycle_job_id": "job_" + "x" * 32},
        {"complete": False},
        {"synthetic": False},
        {"raw": "not-bytes"},
    ],
)
def test_untrusted_frame_metadata_never_produces_cursor(
    tmp_path: Path,
    alter: dict[str, Any],
) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    frame = StreamFrame(RAW, NAME, handle, lid, True, True)
    worker._fixture = lambda *args: replace(frame, **alter)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "failed"
        assert response["errors"][0]["code"] == "INVALID_FRAME"
        assert response["cursor"] is None
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "failed"
    finally:
        live.shutdown()


def test_different_plan_cannot_reuse_same_durable_request(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        result = run(worker, handle, lid, "start")
        assert result["status"] == "ok"
        other = run(worker, handle, lid, "start", max_events=7)
        assert other["status"] == "blocked"
        assert other["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        altered_poll = run(
            worker, handle, lid, "poll", job_id=result["job_id"], cursor=result["cursor"], ttl_s=1
        )
        assert altered_poll["status"] == "blocked"
        assert altered_poll["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_stop_revokes_and_blocks_poll_and_replay_is_not_rerun(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        started = run(worker, handle, lid, "start")
        status = run(worker, handle, lid, "stop", job_id=started["job_id"])
        assert status["status"] == "stopped"
        assert (
            run(worker, handle, lid, "poll", job_id=started["job_id"], cursor=started["cursor"])[
                "errors"
            ][0]["code"]
            == "STOPPED"
        )
        replay = run(worker, handle, lid, "start")
        assert replay["status"] == "stopped"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_ended_session_replayed_as_ended_without_new_capture(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    try:
        start = run(worker, handle, lid, "start")
        poll = run(worker, handle, lid, "poll", job_id=start["job_id"], cursor=start["cursor"])
        assert poll["status"] == "ended"
        assert run(worker, handle, lid, "start")["status"] == "ended"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_wrong_lifecycle_and_remote_serial_never_create_live_stream(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path, active=False)
    try:
        assert run(worker, handle, lid, "start")["errors"][0]["code"] == "UNVERIFIED_TARGET"
        assert run(worker, "physical-serial", lid, "start")["errors"][0]["code"] == "NOT_OWNED"
    finally:
        live.shutdown()


def test_capture_approval_expired_during_callback_never_persists(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)

    def revoke(*args: Any) -> StreamFrame:
        assert worker._approval is not None
        worker._approval = replace(worker._approval, valid_until_epoch=0.0)
        return StreamFrame(RAW, NAME, handle, lid, True, True)

    worker._fixture = revoke
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
        with worker._streams._connect() as db:
            assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0
    finally:
        live.shutdown()


def test_capture_deadline_post_condition_detects_slow_fake_callback(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)

    def delay(*args: Any) -> StreamFrame:
        time.sleep(3.05)
        return StreamFrame(RAW, NAME, handle, lid, True, True)

    worker._fixture = delay
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "TIMEOUT"
    finally:
        live.shutdown()


def test_storage_failure_after_sanitization_revokes_incomplete_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise StreamStoreError("JOB_UNAVAILABLE")

    monkeypatch.setattr(worker._streams, "insert", fail)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "RUNNER_FAILED"
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_job_commit_failure_rolls_back_private_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "complete", fail)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "RUNNER_FAILED"
        with worker._streams._connect() as db:
            assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0
    finally:
        live.shutdown()


def test_wrong_target_cannot_poll_and_disconnect_revokes_staged_records(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    start = run(worker, handle, lid, "start")
    assert start["status"] == "ok"
    live.shutdown()
    result = run(worker, handle, lid, "poll", job_id=start["job_id"], cursor=start["cursor"])
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "UNVERIFIED_TARGET"


def test_stream_expiry_removes_private_rows_on_access(tmp_path: Path) -> None:
    store = LogcatStreamStore(tmp_path / "priv", clock=lambda: 500.0)
    jid, lid = "job_" + "x" * 32, "job_" + "y" * 32
    events = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    start = store.insert(jid, OWNER, "owned-avd", lid, REQ, events, 0, False, 1)
    store._clock = lambda: 502.0
    with pytest.raises(StreamStoreError) as e:
        store.poll(jid, OWNER, "owned-avd", lid, REQ, start["cursor"], 1)
    assert e.value.code == "EXPIRED"
    with store._connect() as db:
        row = db.execute(
            "SELECT state,events FROM logcat_streams WHERE job_id=?", (jid,)
        ).fetchone()
        assert row["state"] == "expired" and row["events"] == "[]"


def test_persisted_record_tampering_cannot_leak_even_with_forged_sha(tmp_path: Path) -> None:
    store = LogcatStreamStore(tmp_path / "priv")
    jid, lid = "job_" + "x" * 32, "job_" + "y" * 32
    events = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    started = store.insert(jid, OWNER, "owned-avd", lid, REQ, events, 0, False, 60)
    poisoned = json.dumps([{"priority": "I", "tag": "McpTest", "message": "password=secret"}])
    with store._tx() as db:
        db.execute(
            "UPDATE logcat_streams SET events=?,content_sha256=? WHERE job_id=?",
            (poisoned, hashlib.sha256(poisoned.encode("ascii")).hexdigest(), jid),
        )
    with pytest.raises(StreamStoreError) as error:
        store.poll(jid, OWNER, "owned-avd", lid, REQ, started["cursor"], 1)
    assert error.value.code == "RECOVERY_REQUIRED"


@pytest.mark.parametrize(
    "invalid",
    [
        {"priority": "X", "tag": "McpTest", "message": "STATE=ready"},
        {"priority": "I", "tag": "Other", "message": "STATE=ready"},
        {"priority": "I", "tag": "McpTest", "message": "TOKEN=abc"},
        {"priority": "I", "tag": "McpTest", "message": "\x1b"},
        {"priority": "I", "tag": "McpTest", "message": "STATE=ready", "extra": "hidden"},
    ],
)
def test_reject_unsafe_stored_events_at_disclosure_boundary(invalid: dict[str, str]) -> None:
    assert not valid_stored_events([invalid])


def test_filter_untrusted_tags_long_lines_and_non_ascii_are_not_retained() -> None:
    raw = (
        line("STATE=ready", tag="McpTest")
        + line("EVENT=connected", tag="Unknown")
        + line("secret=" + "Z" * 1100)
        + line("ALL=汉字")
        + line("STATE=idle", tag="System")
    )
    events, dropped, truncated = parse_events(raw, tag="McpTest", maximum=128)
    assert events == [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    assert dropped == 3 and truncated
    assert b"Z" * 16 not in json.dumps(events).encode()


def test_empty_valid_filtered_stream_is_finite_and_not_misreported() -> None:
    events, dropped, truncated = parse_events(
        line("STATE=ready", tag="McpTest"),
        tag="System",
        maximum=128,
    )
    assert events == [] and dropped == 0 and not truncated


def test_durable_store_denies_oversized_or_invalid_internal_records(tmp_path: Path) -> None:
    store = LogcatStreamStore(tmp_path / "private")
    jid, lid = "job_" + "x" * 32, "job_" + "y" * 32
    values = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    for events, dropped, ttl in [
        ([{"priority": "I", "tag": "McpTest", "message": "SECRET=token"}], 0, 60),
        (values, -1, 60),
        (values, 0, 0),
        (values, 0, 121),
    ]:
        with pytest.raises(StreamStoreError) as error:
            store.insert(jid, OWNER, "owned-avd", lid, REQ, events, dropped, False, ttl)
        assert error.value.code == "INVALID_INPUT"


def test_store_rejects_relative_root_before_private_creation() -> None:
    from pathlib import Path

    with pytest.raises(StreamStoreError) as error:
        LogcatStreamStore(Path("relative-private-root"))
    assert error.value.code == "JOB_UNAVAILABLE"


def test_store_ended_cursor_is_never_replayed(tmp_path: Path) -> None:
    store = LogcatStreamStore(tmp_path / "ended")
    jid, lid = "job_" + "v" * 32, "job_" + "w" * 32
    event = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    started = store.insert(jid, OWNER, "owned", lid, REQ, event, 0, False, 120)
    first = store.poll(jid, OWNER, "owned", lid, REQ, started["cursor"], 1)
    assert first["state"] == "ended"
    with pytest.raises(StreamStoreError) as error:
        store.poll(jid, OWNER, "owned", lid, REQ, started["cursor"], 1)
    assert error.value.code == "ENDED"


def test_store_corrupt_checksum_and_expiring_stop_denied(tmp_path: Path) -> None:
    now = [500.0]
    store = LogcatStreamStore(tmp_path / "checksum", clock=lambda: now[0])
    jid, lid = "job_" + "v" * 32, "job_" + "w" * 32
    event = [{"priority": "I", "tag": "McpTest", "message": "STATE=ready"}]
    started = store.insert(jid, OWNER, "owned", lid, REQ, event, 0, False, 1)
    with store._tx() as db:
        db.execute("UPDATE logcat_streams SET content_sha256=? WHERE job_id=?", ("f" * 64, jid))
    with pytest.raises(StreamStoreError) as error:
        store.poll(jid, OWNER, "owned", lid, REQ, started["cursor"], 1)
    assert error.value.code == "RECOVERY_REQUIRED"
    now[0] = 502
    with pytest.raises(StreamStoreError) as error:
        store.stop(jid, OWNER, "owned", lid, REQ)
    assert error.value.code == "EXPIRED"
    with store._connect() as db:
        row = db.execute(
            "SELECT state,events FROM logcat_streams WHERE job_id=?", (jid,)
        ).fetchone()
        assert row["state"] == "expired" and row["events"] == "[]"


@pytest.mark.parametrize("failure", ["busy", "oserror"])
def test_fixture_lock_denies_before_any_durable_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import android_mcp_host.synthetic_logcat_stream as module

    worker, live, jobs, handle, lid, calls = builder(tmp_path)

    def fake_lock(*args: Any) -> Any:
        if failure == "oserror":
            raise OSError("simulated fixture lock creation error")
        return None

    monkeypatch.setattr(module, "claim_fixture_lock", fake_lock)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == (
            "JOB_UNAVAILABLE" if failure == "oserror" else "RECOVERY_REQUIRED"
        )
        assert calls == []
    finally:
        live.shutdown()


def test_durable_failed_capture_cannot_be_polled_as_success(tmp_path: Path) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    worker._fixture = lambda *args: StreamFrame(RAW, NAME, "wrong-avd", lid, True, True)
    try:
        failed = run(worker, handle, lid, "start")
        assert failed["status"] == "failed"
        result = run(
            worker, handle, lid, "poll", job_id=failed["job_id"], cursor="cur_000_" + "a" * 32
        )
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == "RECOVERY_REQUIRED"
    finally:
        live.shutdown()


def test_consent_revoked_after_private_row_insert_discards_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    original = worker._streams.insert

    def revoke_after_store(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        assert worker._approval is not None
        worker._approval = replace(worker._approval, valid_until_epoch=0.0)
        return result

    monkeypatch.setattr(worker._streams, "insert", revoke_after_store)
    try:
        response = run(worker, handle, lid, "start")
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "CANCELLED"
        with worker._streams._connect() as db:
            assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0
    finally:
        live.shutdown()


def test_fixture_disconnected_while_parsing_never_writes_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import android_mcp_host.synthetic_logcat_stream as module

    worker, live, jobs, handle, lid, calls = builder(tmp_path)
    original = module.parse_events

    def disconnect_during_parse(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        live.shutdown()
        return result

    monkeypatch.setattr(module, "parse_events", disconnect_during_parse)
    response = run(worker, handle, lid, "start")
    assert response["status"] == "uncertain"
    assert response["errors"][0]["code"] == "UNVERIFIED_TARGET"
    with worker._streams._connect() as db:
        assert db.execute("SELECT count(*) FROM logcat_streams").fetchone()[0] == 0

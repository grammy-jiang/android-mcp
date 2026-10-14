"""H5.c deterministic hostile traces, durable races, cancellation and recovery."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_perfetto_trace_job import ART_OWNER, PROF, RAW, builder, frame, submit

from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.perfetto_trace_support import (
    MARKER,
    InvalidTrace,
    sanitize_trace,
)
from android_mcp_host.synthetic_perfetto import PerfettoFrame, PerfettoService


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"hello",
        b"not-perfetto\n",
        MARKER,
        MARKER + b"garbage\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1\x00\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1\r\n",
        MARKER + b"\xff\xfe\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1\n" + b"bad:" * 10000,
    ],
)
def test_t_h5c_03_malformed_untrusted_trace_fails_without_artifact(
    tmp_path: Path,
    bad: bytes,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, payload=bad)
    try:
        outcome = submit(worker, handle, lid, "capture")
        assert outcome["status"] == "failed"
        assert outcome["errors"][0]["code"] in ("BAD_TRACE", "TRACE_TOO_LARGE")
        assert outcome["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "bad",
    [
        MARKER + b"ts_ms=9999;event=cpu_slice;value=1\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1000001\n",
        MARKER + b"ts_ms=0;event=kernel_syscall;value=1\n",
        MARKER + b"ts_ms=100;event=cpu_slice;value=1\nts_ms=99;event=cpu_slice;value=2\n",
        MARKER + b"ts_ms=0;event=frame_present;value=1\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=01\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=-1\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=99999999\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1\n" + b"x" * 170 + b"\n",
        MARKER + b"ts_ms=0;event=cpu_slice;value=1\n" + b"\x1b[31m\n",
        MARKER + b"x\n" * 257,
    ],
)
def test_trace_parser_rejects_unsafe_sequence(tmp_path: Path, bad: bytes) -> None:
    with pytest.raises(InvalidTrace):
        sanitize_trace(bad, profile=PROF, duration_s=3, max_bytes=131072)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        42,
        {},
        bytearray(MARKER),
        "MCP_SYNTHETIC_TRACE_V1\n",
    ],
)
def test_parser_rejects_nonbytes_without_disk_touch(bad: Any) -> None:
    with pytest.raises(InvalidTrace):
        sanitize_trace(bad, profile=PROF, duration_s=3, max_bytes=131072)


@pytest.mark.parametrize(
    "wrong",
    [
        {"profile": "sched-lite-v1;--config=/tmp/evil"},
        {"profile": "fake"},
        {"duration_s": 0},
        {"duration_s": True},
        {"max_bytes": 8},
        {"max_bytes": 131073},
        {"ttl_s": 0},
        {"ttl_s": True},
        {"ttl_s": 301},
    ],
)
def test_t_h5c_03_profile_and_budget_denied_before_reader(
    tmp_path: Path,
    wrong: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        result = submit(worker, handle, lid, "capture", **wrong)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] in ("INVALID_INPUT", "INVALID_PROFILE")
        assert calls == []
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "bad",
    [
        {"owner": "other-owner"},
        {"avd_handle": "other-handle"},
        {"lifecycle_job_id": "job_" + "z" * 32},
        {"profile": "frames-lite-v1"},
        {"purpose": "other-purpose"},
        {"valid_until_epoch": 0.0},
        {"valid_until_epoch": float("nan")},
        {"ttl_s": 0},
        {"ttl_s": True},
    ],
)
def test_t_h5c_02_approval_must_match_all_grant_dimensions(
    tmp_path: Path,
    bad: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        assert worker._approval is not None
        worker._approval = replace(worker._approval, **bad)
        response = submit(worker, handle, lid, "capture")
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "field",
    [
        {"avd_name": "some-host"},
        {"avd_handle": "USB_abc"},
        {"lifecycle_job_id": "job_" + "q" * 32},
        {"profile": "frames-lite-v1"},
        {"duration_s": 10},
        {"fixture_version": "v10"},
        {"complete": False},
        {"synthetic": False},
        {"payload": "not bytes"},
    ],
)
def test_t_h5c_03_wrong_frame_provenance_denied(
    tmp_path: Path,
    field: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    original = frame(RAW, NAME, handle, lid, PROF, 3)
    worker._fixture = lambda *args: replace(original, **field)
    try:
        response = submit(worker, handle, lid, "capture")
        assert response["status"] == "failed"
        assert response["errors"][0]["code"] == "BAD_FRAME"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "failed"
    finally:
        live.shutdown()


def test_t_h5c_05_finite_fixture_is_cancelled_and_releases_all_artifacts(tmp_path: Path) -> None:
    started = threading.Event()

    def slow(
        name: str,
        handle: str,
        lid: str,
        profile: str,
        duration: int,
        cap: int,
        timeout: float,
        stop: threading.Event,
    ) -> PerfettoFrame:
        started.set()
        assert stop.wait(timeout=1.5)
        return frame(RAW, name, handle, lid, profile, duration)

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, fixture=slow)
    result: list[dict[str, Any]] = []
    try:
        capture = threading.Thread(
            target=lambda: result.append(submit(worker, handle, lid, "capture"))
        )
        capture.start()
        assert started.wait(1.5)
        active = [x for x in jobs.list_status(OWNER) if x["job_id"] != lid]
        assert len(active) == 1 and active[0]["state"] == "running"
        cancelled = submit(worker, handle, lid, "cancel", job_id=active[0]["job_id"])
        assert cancelled["status"] == "uncertain"
        assert cancelled["errors"][0]["code"] == "CANCELLED"
        repeated = submit(worker, handle, lid, "cancel", job_id=active[0]["job_id"])
        assert repeated["status"] == "uncertain"
        assert repeated["errors"][0]["code"] == "CANCELLED"
        capture.join(2)
        assert not capture.is_alive()
        assert result[0]["status"] == "uncertain"
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, active[0]["job_id"])["job"]["state"] == "uncertain"
        assert submit(worker, handle, lid, "capture")["errors"][0]["code"] == "RECOVERY_REQUIRED"
    finally:
        live.shutdown()


def test_t_h5c_05_disconnect_before_trace_can_complete(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def lose(*args: Any) -> PerfettoFrame:
        live.shutdown()
        return frame(RAW, NAME, handle, lid, PROF, 3)

    worker._fixture = lose
    outcome = submit(worker, handle, lid, "capture")
    assert outcome["status"] == "uncertain"
    assert outcome["errors"][0]["code"] == "UNVERIFIED_TARGET"
    assert store.list_metadata(ART_OWNER) == []


def test_t_h5c_05_consent_expires_while_fixture_runs(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def revoke(*args: Any) -> PerfettoFrame:
        assert worker._approval is not None
        worker._approval = replace(worker._approval, valid_until_epoch=0)
        return frame(RAW, NAME, handle, lid, PROF, 3)

    worker._fixture = revoke
    try:
        outcome = submit(worker, handle, lid, "capture")
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "CONSENT_REQUIRED"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h5c_05_fixture_crash_or_storage_error_is_uncertain(tmp_path: Path) -> None:
    def crash(*args: Any) -> Any:
        raise OSError("synthetic private error user@example.com")

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, fixture=crash)
    try:
        outcome = submit(worker, handle, lid, "capture")
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "RUNNER_FAILED"
        assert "user@example.com" not in json.dumps(outcome)
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h5c_05_commit_after_private_artifacts_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise JobStoreError("STORAGE_FAILURE")

    monkeypatch.setattr(jobs, "complete", fail)
    try:
        outcome = submit(worker, handle, lid, "capture")
        assert outcome["status"] == "uncertain"
        assert outcome["errors"][0]["code"] == "RUNNER_FAILED"
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h5c_06_reboot_restart_replays_only_verified_receipt(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        success = submit(worker, handle, lid, "capture")
        assert success["status"] == "ok"
        second = PerfettoService(
            live.provisioner,
            live,
            jobs,
            store,
            owner=OWNER,
            artifact_owner=ART_OWNER,
            approval=worker._approval,
            fixture_trace=lambda *args: pytest.fail("Re-executed after confirmed success"),
        )
        replay = submit(second, handle, lid, "capture")
        assert replay["status"] == "ok"
        assert replay["artifact_handle"] == success["artifact_handle"]
        assert replay["sha256"] == success["sha256"]
    finally:
        live.shutdown()


def test_t_h5c_06_replay_corruption_never_claims_success(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        success = submit(worker, handle, lid, "capture")
        assert success["status"] == "ok"
        store.revoke(ART_OWNER, success["artifact_handle"])
        replay = submit(worker, handle, lid, "capture")
        assert replay["status"] == "uncertain"
        assert replay["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_cancel_wrong_job_or_request_cannot_touch_other_work(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        success = submit(worker, handle, lid, "capture")
        assert success["status"] == "ok"
        wrong = submit(worker, handle, lid, "cancel", job_id="job_" + "x" * 32)
        assert wrong["errors"][0]["code"] == "NOT_ACTIVE"
        wrong_request = submit(
            worker, handle, lid, "cancel", request="wrong-request", job_id=success["job_id"]
        )
        assert wrong_request["errors"][0]["code"] in ("NOT_ACTIVE", "IDEMPOTENCY_CONFLICT")
        finished = submit(worker, handle, lid, "cancel", job_id=success["job_id"])
        assert finished["status"] == "blocked"
        assert finished["errors"][0]["code"] == "NOT_ACTIVE"
        assert jobs.status(OWNER, success["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


def test_bad_trace_replay_is_failed_no_silent_rerun(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, payload=MARKER + b"bad\n")
    try:
        bad = submit(worker, handle, lid, "capture")
        assert bad["status"] == "failed"
        replay = submit(worker, handle, lid, "capture")
        assert replay["status"] == "failed"
        assert replay["errors"][0]["code"] == "BAD_TRACE"
        assert len(calls) == 1
    finally:
        live.shutdown()


def test_negative_timestamp_forged_sanitized_trace_is_rejected() -> None:
    from android_mcp_host.perfetto_trace_support import valid_sanitized_trace

    forged = {
        "format": "mcp-synthetic-perfetto-v1",
        "profile": PROF,
        "requested_duration_s": 3,
        "synthetic_fixture_only": True,
        "samples": [{"ts_ms": -1, "event": "cpu_slice", "value": 1}],
    }
    raw = json.dumps(forged, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert valid_sanitized_trace(raw, profile=PROF, duration_s=3) is False


def test_independent_approval_alone_never_enables_production_trace_reader(
    tmp_path: Path,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    worker._fixture = None
    try:
        denied = submit(worker, handle, lid, "capture")
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert denied["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert calls == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()

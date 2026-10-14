"""H5.c deep synthetic trace parser and replay integrity tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_perfetto_trace_job import ART_OWNER, PROF, REQ, builder, submit

from android_mcp_host.perfetto_trace_receipts import replay_trace
from android_mcp_host.perfetto_trace_support import (
    MARKER,
    MAX_SAMPLES,
    MAX_SANITIZED_BYTES,
    InvalidTrace,
    sanitize_trace,
    valid_sanitized_trace,
)
from android_mcp_host.private_artifact_support import ArtifactStoreError


def serial(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii")


def valid() -> tuple[bytes, dict[str, Any]]:
    trace, count, removed = sanitize_trace(
        MARKER + b"ts_ms=0;event=cpu_slice;value=0\n" + b"ts_ms=10;event=counter;value=3\n",
        profile=PROF,
        duration_s=3,
        max_bytes=131072,
    )
    assert count == 2 and removed == 0
    return trace, json.loads(trace)


@pytest.mark.parametrize(
    "alter",
    [
        lambda d: d.update({"format": "untrusted-trace"}),
        lambda d: d.update({"synthetic_fixture_only": False}),
        lambda d: d.update({"profile": "frames-lite-v1"}),
        lambda d: d.update({"requested_duration_s": 2}),
        lambda d: d.update({"samples": []}),
        lambda d: d.update({"samples": "nonnumeric"}),
        lambda d: d.update({"unexpected": "secret"}),
        lambda d: d["samples"][0].update({"value": "2"}),
        lambda d: d["samples"][0].update({"value": True}),
        lambda d: d["samples"][0].update({"value": -1}),
        lambda d: d["samples"][0].update({"value": 1000001}),
        lambda d: d["samples"][0].update({"event": "kernel_root"}),
        lambda d: d["samples"][0].update({"event": 123}),
        lambda d: d["samples"][0].update({"ts_ms": True}),
        lambda d: d["samples"][0].update({"ts_ms": -1}),
        lambda d: d["samples"][0].update({"ts_ms": 10000}),
        lambda d: d["samples"][0].update({"token": "credential"}),
        lambda d: d["samples"][1].update({"ts_ms": -1}),
    ],
)
def test_replay_rejects_forged_private_synthetic_trace_fields(alter: Any) -> None:
    raw, original = valid()
    data = deepcopy(original)
    alter(data)
    assert not valid_sanitized_trace(serial(data), profile=PROF, duration_s=3)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        object(),
        {"samples": []},
        b"not-json",
        b"[]",
        b"{}",
        b"\xff",
        b"Z" * 32769,
    ],
)
def test_replay_rejects_invalid_json_storage(raw: Any) -> None:
    assert valid_sanitized_trace(raw, profile=PROF, duration_s=3) is False


def test_replay_rejects_noncanonical_json_and_even_valid_whitespace() -> None:
    raw, parsed = valid()
    assert valid_sanitized_trace(raw, profile=PROF, duration_s=3)
    assert not valid_sanitized_trace(json.dumps(parsed).encode(), profile=PROF, duration_s=3)


def test_parser_truncates_but_removes_host_token_lines_before_any_storage() -> None:
    rows = b"ts_ms=1;event=cpu_slice;value=0\n" * 130
    raw = MARKER + rows + b"PASSWORD=secret.host.example.com\n"
    sanitized, count, removed = sanitize_trace(raw, profile=PROF, duration_s=3, max_bytes=131072)
    assert count == MAX_SAMPLES
    assert removed == 3
    assert len(sanitized) <= MAX_SANITIZED_BYTES
    assert b"secret.host.example.com" not in sanitized
    assert valid_sanitized_trace(sanitized, profile=PROF, duration_s=3)


def test_frames_profile_accepts_only_fixed_frame_events() -> None:
    raw = (
        MARKER
        + b"ts_ms=0;event=frame_present;value=10\n"
        + b"ts_ms=120;event=frame_dropped;value=2\n"
    )
    saved, count, removed = sanitize_trace(
        raw, profile="frames-lite-v1", duration_s=3, max_bytes=131072
    )
    assert count == 2 and removed == 0
    assert valid_sanitized_trace(saved, profile="frames-lite-v1", duration_s=3)
    assert not valid_sanitized_trace(saved, profile=PROF, duration_s=3)
    with pytest.raises(InvalidTrace):
        sanitize_trace(raw, profile=PROF, duration_s=3, max_bytes=131072)


def test_parser_drops_unknown_valid_ascii_payload_not_trace_events() -> None:
    data = MARKER + b"UNTRUSTED_FIELD=discard-me\n" + b"ts_ms=0;event=cpu_slice;value=0\n"
    out, count, removed = sanitize_trace(data, profile=PROF, duration_s=3, max_bytes=131072)
    assert count == 1 and removed == 1
    assert b"UNTRUSTED_FIELD" not in out and b"discard-me" not in out


def test_receipt_forgery_and_corrupt_digests_cannot_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        original = submit(worker, handle, lid, "capture")
        assert original["status"] == "ok"
        job = jobs.lookup_request(
            OWNER,
            worker._slot(lid),
            __import__(
                "android_mcp_host.perfetto_trace_support", fromlist=["plan_digest"]
            ).plan_digest(handle, lid, REQ, PROF, 3, 131072, 60),
            handle,
        )
        assert job is not None
        good = store.read(ART_OWNER, original["receipt_handle"])
        real_read = store.read
        for item in [
            {"job_id": "job_" + "x" * 32},
            {"purpose": "other"},
            {"avd_handle": "other"},
            {"lifecycle_job_id": "job_" + "x" * 32},
            {"profile": "frames-lite-v1"},
            {"fixture_version": "unknown"},
            {"sample_count": True},
            {"sample_count": 999},
            {"retention_seconds": 0},
            {"trace_format": "not-perfetto"},
            {"synthetic_fixture_only": False},
            {"sanitized_only": False},
            {"size_bytes": 99999},
        ]:
            forged = json.loads(good)
            forged.update(item)

            forged_blob = serial(forged)

            def read(owner: str, art: str, _blob: bytes = forged_blob) -> bytes:
                if art == original["receipt_handle"]:
                    return _blob
                return real_read(owner, art)

            monkeypatch.setattr(store, "read", read)
            response = replay_trace(
                store,
                ART_OWNER,
                job,
                name=NAME,
                handle=handle,
                lifecycle=lid,
                profile=PROF,
                duration_s=3,
                max_bytes=131072,
            )
            assert response["status"] == "uncertain"
            assert response["errors"][0]["code"] == "ARTIFACT_EXPIRED"
        monkeypatch.setattr(store, "read", real_read)
    finally:
        live.shutdown()


def test_replay_rejects_wrong_metadata_and_missing_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        original = submit(worker, handle, lid, "capture")
        assert original["status"] == "ok"
        original_meta = store.public_metadata

        def fake_meta(*args: Any, **kwargs: Any) -> dict[str, Any]:
            data = original_meta(*args, **kwargs)
            data["artifact"]["mime_type"] = "application/octet-stream"
            return data

        monkeypatch.setattr(store, "public_metadata", fake_meta)
        response = submit(worker, handle, lid, "capture")
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_missing_private_artifact_denies_success(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        ok = submit(worker, handle, lid, "capture")
        assert ok["status"] == "ok"
        store.revoke(ART_OWNER, ok["receipt_handle"])
        denied = submit(worker, handle, lid, "capture")
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()


def test_storage_read_fault_never_surfaces_host_exception_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        success = submit(worker, handle, lid, "capture")
        assert success["status"] == "ok"

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise ArtifactStoreError("INTEGRITY_FAIL")

        monkeypatch.setattr(store, "read", fail)
        reply = submit(worker, handle, lid, "capture")
        assert reply["status"] == "uncertain"
        assert reply["errors"][0]["code"] == "ARTIFACT_EXPIRED"
    finally:
        live.shutdown()

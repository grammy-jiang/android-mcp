"""H5.c six mandatory private synthetic Perfetto acceptance scenarios."""

from __future__ import annotations

import asyncio
import hashlib
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

from android_mcp_host.perfetto_trace_support import (
    MARKER,
    TRACE_VERSION,
    valid_sanitized_trace,
)
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server
from android_mcp_host.synthetic_perfetto import (
    PerfettoApproval,
    PerfettoFrame,
    PerfettoService,
    get_perfetto_schema,
)

ART_OWNER = "synthetic-perfetto-private"
REQ = "synthetic-perfetto-request-001"
RAW = (
    MARKER
    + b"ts_ms=0;event=cpu_slice;value=5\n"
    + b"ts_ms=100;event=sched_switch;value=12\n"
    + b"SECRET=private-user@example.com\n"
    + b"ts_ms=200;event=counter;value=10\n"
)
PROF = "sched-lite-v1"


def frame(
    data: bytes, name: str, handle: str, lid: str, profile: str, duration: int
) -> PerfettoFrame:
    return PerfettoFrame(
        data,
        name,
        handle,
        lid,
        profile,
        duration,
        "mcp-fixture-1",
        True,
        True,
    )


def builder(
    tmp_path: Path,
    *,
    approved: bool = True,
    active: bool = True,
    debuggable: bool = True,
    supported: bool = True,
    profile: str = PROF,
    payload: bytes = RAW,
    fixture: Any = None,
) -> tuple[PerfettoService, Any, Any, PrivateArtifactStore, str, str, list[Any]]:
    live, handle, jobs, _ = engine(tmp_path, backend=active, readiness_timeout=5.0)
    lid = "job_" + "z" * 32
    if active:
        running = live.run("start", NAME, handle, request_id=START_REQUEST)
        assert running["status"] == "ok"
        lid = running["job_id"]
    grant = (
        PerfettoApproval(
            OWNER,
            handle,
            lid,
            profile,
            "private-synthetic-perfetto",
            time.time() + 180,
            120,
            debuggable,
            supported,
        )
        if approved
        else None
    )
    artifacts = PrivateArtifactStore(tmp_path / "private-perfetto")
    calls: list[Any] = []
    if fixture is None:

        def fixture(
            name: str,
            avd_handle: str,
            lifecycle_id: str,
            profile: str,
            duration_s: int,
            max_bytes: int,
            timeout: float,
            stop: threading.Event,
        ) -> PerfettoFrame:
            calls.append((name, avd_handle, lifecycle_id, profile, duration_s, max_bytes, timeout))
            assert not stop.is_set()
            return frame(payload, name, avd_handle, lifecycle_id, profile, duration_s)

    worker = PerfettoService(
        live.provisioner,
        live,
        jobs,
        artifacts,
        owner=OWNER,
        artifact_owner=ART_OWNER,
        approval=grant,
        fixture_trace=fixture,
    )
    return worker, live, jobs, artifacts, handle, lid, calls


def submit(
    worker: PerfettoService,
    handle: str,
    lid: str,
    action: str,
    *,
    request: str = REQ,
    **kwargs: Any,
) -> dict[str, Any]:
    return worker.submit(action, NAME, handle, lid, request_id=request, **kwargs)


def check(value: dict[str, Any]) -> None:
    Draft202012Validator(get_perfetto_schema()).validate(value)


def test_t_h5c_01_private_synthetic_trace_is_sanitized_before_storage(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        result = submit(worker, handle, lid, "capture")
        check(result)
        assert result["status"] == "ok"
        assert result["trace_state"] == "synthetic_sanitized"
        assert result["format"] == TRACE_VERSION
        assert result["sample_count"] == 3
        assert result["redacted_lines"] == 1
        assert result["retention_seconds"] == 60
        assert result["raw_trace_returned"] is False
        assert result["real_perfetto_enabled"] is False
        assert result["physical_device_reads_enabled"] is False
        assert result["artifact_handle"].startswith("art_")
        assert result["receipt_handle"].startswith("art_")
        assert calls == [(NAME, handle, lid, PROF, 3, 131072, 3.0)]
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "succeeded"
        saved = store.read(ART_OWNER, result["artifact_handle"])
        assert hashlib.sha256(saved).hexdigest() == result["sha256"]
        assert valid_sanitized_trace(saved, profile=PROF, duration_s=3)
        assert len(json.loads(saved)["samples"]) == 3
        for item in store.list_metadata(ART_OWNER):
            raw = store.read(ART_OWNER, item["handle"])
            assert b"private-user@example.com" not in raw
            assert b"SECRET=" not in raw
        assert "private-user@example.com" not in json.dumps(result)
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("approved", "debuggable", "supported", "code"),
    [
        (False, True, True, "CONSENT_REQUIRED"),
        (True, False, True, "NOT_DEBUGGABLE"),
        (True, True, False, "TRACE_UNSUPPORTED"),
    ],
)
def test_t_h5c_02_denial_before_read(
    tmp_path: Path,
    approved: bool,
    debuggable: bool,
    supported: bool,
    code: str,
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(
        tmp_path, approved=approved, debuggable=debuggable, supported=supported
    )
    try:
        result = submit(worker, handle, lid, "capture")
        check(result)
        assert result["status"] == "blocked"
        assert result["errors"][0]["code"] == code
        assert calls == []
        assert store.list_metadata(ART_OWNER) == []
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h5c_02_unowned_or_inactive_device_never_invokes_fixture(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, active=False)
    try:
        assert submit(worker, handle, lid, "capture")["errors"][0]["code"] == "UNVERIFIED_TARGET"
        assert (
            submit(worker, "physical-device-serial", lid, "capture")["errors"][0]["code"]
            == "NOT_OWNED"
        )
        assert calls == []
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "options",
    [
        {"profile": "../../system"},
        {"profile": "sched-lite-v1 --config=/tmp/evil"},
        {"profile": "unknown"},
        {"profile": ""},
        {"duration_s": 0},
        {"duration_s": 11},
        {"duration_s": True},
        {"max_bytes": 0},
        {"max_bytes": 131073},
        {"ttl_s": 301},
        {"ttl_s": True},
    ],
)
def test_t_h5c_03_bounded_profile_and_flags_are_checked_before_fixture(
    tmp_path: Path,
    options: dict[str, Any],
) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        denied = submit(worker, handle, lid, "capture", **options)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] in ("INVALID_INPUT", "INVALID_PROFILE")
        assert calls == []
        assert store.list_metadata(ART_OWNER) == []
    finally:
        live.shutdown()


def test_t_h5c_04_private_trace_no_secret_or_untrusted_path_in_reply(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(
        tmp_path,
        payload=(
            MARKER
            + b"username=private-user@example.com\n"
            + b"ts_ms=0;event=cpu_slice;value=0\n"
            + b"password=top-secret\n"
            + b"ts_ms=100;event=counter;value=1\n"
        ),
    )
    try:
        outcome = submit(worker, handle, lid, "capture")
        assert outcome["status"] == "ok"
        assert outcome["redacted_lines"] == 2
        text = json.dumps(outcome) + store.read(ART_OWNER, outcome["artifact_handle"]).decode()
        assert "private-user@example.com" not in text
        assert "top-secret" not in text
        assert str(tmp_path) not in text
    finally:
        live.shutdown()


def test_t_h5c_05_timeout_uncertain_and_no_private_partial_output(tmp_path: Path) -> None:
    def timedout(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fake-perfetto"], 0.1)

    worker, live, jobs, store, handle, lid, calls = builder(tmp_path, fixture=timedout)
    try:
        result = submit(worker, handle, lid, "capture")
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "TIMEOUT"
        assert result["artifact_handle"] is None
        assert store.list_metadata(ART_OWNER) == []
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
        assert submit(worker, handle, lid, "capture")["errors"][0]["code"] == "RECOVERY_REQUIRED"
    finally:
        live.shutdown()


def test_t_h5c_06_durable_receipt_exact_provenance_and_replay(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)
    try:
        first = submit(worker, handle, lid, "capture")
        replay = submit(worker, handle, lid, "capture")
        check(replay)
        assert replay["status"] == "ok"
        assert replay["artifact_handle"] == first["artifact_handle"]
        assert replay["receipt_handle"] == first["receipt_handle"]
        assert len(calls) == 1
        receipt = json.loads(store.read(ART_OWNER, first["receipt_handle"]))
        assert receipt["purpose"] == "h5c-sanitized-synthetic-perfetto-v1"
        assert receipt["profile"] == PROF
        assert receipt["duration_s"] == 3
        assert receipt["fixture_version"] == "mcp-fixture-1"
        assert receipt["avd_handle"] == handle
        assert receipt["lifecycle_job_id"] == lid
        assert receipt["sha256"] == first["sha256"]
        assert (
            submit(worker, handle, lid, "capture", duration_s=4)["errors"][0]["code"]
            == "IDEMPOTENCY_CONFLICT"
        )
        assert (
            submit(worker, handle, lid, "capture", request="other-request")["status"] == "blocked"
        )
    finally:
        live.shutdown()


def test_t_h5c_06_inprocess_fastmcp_exact_schema_and_production_denial(tmp_path: Path) -> None:
    worker, live, jobs, store, handle, lid, calls = builder(tmp_path)

    async def check_client() -> None:
        async with Client(create_server()) as base:
            original = {x.name: x for x in await base.list_tools()}
        async with Client(create_server(perfetto_worker=worker)) as client:
            tools = {x.name: x for x in await client.list_tools()}
            assert set(tools) == {*original, "host_perfetto_trace"}
            assert all(original[key] == tools[key] for key in original)
            tool = tools["host_perfetto_trace"]
            assert tool.output_schema == get_perfetto_schema()
            assert tool.annotations.destructive_hint is True
            args = {"avd_name": NAME, "avd_handle": handle, "lifecycle_job_id": lid}
            plan = await client.call_tool("host_perfetto_trace", {"action": "plan", **args})
            assert plan.structured_content["status"] == "planned"
            result = await client.call_tool(
                "host_perfetto_trace", {"action": "capture", "request_id": REQ, **args}
            )
            assert not result.is_error
            check(result.structured_content)
            assert result.structured_content["status"] == "ok"
            assert result.structured_content["raw_trace_returned"] is False

    try:
        asyncio.run(check_client())
    finally:
        live.shutdown()

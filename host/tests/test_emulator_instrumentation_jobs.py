"""H3.e six mandatory exact synthetic-only instrumentation job cases."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from jsonschema import Draft202012Validator
from test_avd_provisioning import NAME, OWNER
from test_emulator_lifecycle_jobs import REQUEST as LIFECYCLE_REQUEST
from test_emulator_lifecycle_jobs import engine

from android_mcp_host.command_runner import RunResult
from android_mcp_host.private_artifact_store import PrivateArtifactStore
from android_mcp_host.server import create_server

COMPONENT = "org.example.synthetic.test/androidx.test.runner.AndroidJUnitRunner"
APK_MIME = "application/vnd.android.package-archive"
INSTRUMENT_OWNER = "instrument-private-owner"
RUN_REQUEST = "instrumentation-test-run-001"


def synthetic_test_apk() -> bytes:
    stream = io.BytesIO()
    manifest = (
        b'<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        b'package="org.example.synthetic.test" android:versionCode="1" '
        b'android:versionName="1.0"><uses-permission '
        b'android:name="android.permission.INTERNET" /></manifest>'
    )
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("AndroidManifest.xml", manifest)
        output.writestr("resources.arsc", b"synthetic fixture")
    return stream.getvalue()


def setup_fixture(
    tmp_path: Path,
    *,
    running: bool = True,
    runner: Any = None,
) -> tuple[Any, Any, Any, PrivateArtifactStore, str, str, str, str]:
    from android_mcp_host.emulator_instrumentation_jobs import InstrumentationJobs

    lifecycle, avd_handle, jobs, backend = engine(tmp_path, backend=running)
    source_job = "job_" + "x" * 32
    if running:
        started = lifecycle.run("start", NAME, avd_handle, request_id=LIFECYCLE_REQUEST)
        assert started["status"] == "ok"
        source_job = started["job_id"]
    store = PrivateArtifactStore(tmp_path / "private-artifacts")
    apk = synthetic_test_apk()
    record = store.put(INSTRUMENT_OWNER, apk, mime_type=APK_MIME)
    sha = hashlib.sha256(apk).hexdigest()
    task = InstrumentationJobs(
        lifecycle.provisioner,
        lifecycle,
        jobs,
        store,
        owner=OWNER,
        artifact_owner=INSTRUMENT_OWNER,
        fixture_runner=runner,
    )
    return task, lifecycle, jobs, store, avd_handle, source_job, record["handle"], sha


def success(argv: Any, timeout: float, limit: int) -> RunResult:
    assert timeout <= 10 and limit <= 8192
    return RunResult(0, '{"passed":2,"failed":0,"total":2,"synthetic":true}', "", False)


def test_t_h3e_01_verified_fake_emulator_and_private_apk_produce_report(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def runner(argv: Any, seconds: float, limit: int) -> RunResult:
        calls.append(list(argv))
        return success(argv, seconds, limit)

    task, live, jobs, store, handle, lifecycle_id, apk_handle, sha = setup_fixture(
        tmp_path, runner=runner
    )
    try:
        plan = task.submit("plan", NAME, handle, lifecycle_id, apk_handle, sha, COMPONENT)
        assert plan["status"] == "planned" and plan["real_instrumentation_enabled"] is False
        report = task.submit(
            "run",
            NAME,
            handle,
            lifecycle_id,
            apk_handle,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert report["status"] == "ok"
        assert report["state"] == "succeeded"
        assert report["passed"] == 2 and report["failed"] == 0
        assert report["report_handle"].startswith("art_")
        assert report["job_id"].startswith("job_")
        assert report["target"] == "disposable_emulator_only"
        assert report["synthetic_fixture_only"] is True
        assert report["physical_device_writes_enabled"] is False
        assert calls == [
            [
                "fixture-instrumentation",
                "--avd",
                NAME,
                "--lifecycle-job",
                lifecycle_id,
                "--apk-sha256",
                sha,
                "--component",
                COMPONENT,
            ]
        ]
        contents = json.loads(store.read(INSTRUMENT_OWNER, report["report_handle"]))
        assert contents["state"] == "succeeded"
        assert contents["target_avd_handle"] == handle
        assert contents["apk_sha256"] == sha
        assert contents["case_total"] == 2
        assert contents["passed"] == 2
        assert jobs.status(OWNER, report["job_id"])["job"]["state"] == "succeeded"
        assert str(tmp_path) not in json.dumps(report)
    finally:
        live.shutdown()


def test_t_h3e_02_physical_target_or_wrong_avd_denied_before_execution(
    tmp_path: Path,
) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        raise AssertionError("No physical-device execution allowed")

    task, live, jobs, store, handle, lid, artifact, sha = setup_fixture(tmp_path, runner=runner)
    try:
        for avd, opaque, job in (
            ("user-native-api36", handle, lid),
            (NAME, "mcpavd_" + "z" * 32, lid),
            (NAME, handle, "job_" + "z" * 32),
        ):
            denied = task.submit(
                "run", avd, opaque, job, artifact, sha, COMPONENT, request_id=RUN_REQUEST
            )
            assert denied["status"] == "blocked"
        assert calls == [0]
        assert len(jobs.list_status(OWNER)) == 1  # Only the existing fake lifecycle
    finally:
        live.shutdown()


def test_t_h3e_03_component_flags_digest_or_apk_denied(tmp_path: Path) -> None:
    task, live, jobs, store, handle, lid, artifact, sha = setup_fixture(tmp_path, runner=success)
    try:
        for component, digest, token in (
            ("malicious -e class", sha, artifact),
            ("org.example/.Hidden; rm -rf /", sha, artifact),
            (COMPONENT, "0" * 64, artifact),
            (COMPONENT, sha, "art_" + "x" * 32),
        ):
            blocked = task.submit(
                "run",
                NAME,
                handle,
                lid,
                token,
                digest,
                component,
                request_id=RUN_REQUEST,
            )
            assert blocked["status"] == "blocked"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_t_h3e_04_failed_instrumentation_is_not_successful_job(tmp_path: Path) -> None:
    def failed(*args: Any) -> RunResult:
        return RunResult(
            1,
            '{"passed":1,"failed":1,"total":2,"synthetic":true}',
            "PRIVATE PII SHOULD NOT BE STORED",
            False,
        )

    task, live, jobs, store, handle, lid, artifact, sha = setup_fixture(tmp_path, runner=failed)
    try:
        result = task.submit(
            "run", NAME, handle, lid, artifact, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert result["status"] == "failed" and result["state"] == "failed"
        assert result["passed"] == 1 and result["failed"] == 1
        assert result["report_handle"].startswith("art_")
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "failed"
        assert "PRIVATE PII" not in json.dumps(result)
        assert "PRIVATE PII" not in store.read(INSTRUMENT_OWNER, result["report_handle"]).decode()
    finally:
        live.shutdown()


def test_t_h3e_05_timeout_and_duplicate_request_never_retry(tmp_path: Path) -> None:
    calls = [0]

    def timeout(*args: Any) -> RunResult:
        calls[0] += 1
        raise subprocess.TimeoutExpired(["synthetic-instrumentation"], 0.01)

    task, live, jobs, store, handle, lid, artifact, sha = setup_fixture(tmp_path, runner=timeout)
    try:
        initial = task.submit(
            "run", NAME, handle, lid, artifact, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert initial["status"] == "uncertain"
        assert jobs.status(OWNER, initial["job_id"])["job"]["state"] == "uncertain"
        replay = task.submit(
            "run", NAME, handle, lid, artifact, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert replay["job_id"] == initial["job_id"]
        assert replay["status"] == "uncertain"
        assert (
            task.submit(
                "run", NAME, handle, lid, artifact, sha, COMPONENT, request_id="new-instrument-run"
            )["status"]
            == "blocked"
        )
        assert calls == [1]
    finally:
        live.shutdown()


def test_t_h3e_06_mcp_contract_default_off_and_private_status(tmp_path: Path) -> None:
    from android_mcp_host.emulator_instrumentation_jobs import get_instrumentation_schema

    task, live, jobs, store, handle, lid, artifact, sha = setup_fixture(tmp_path, running=False)

    async def verify() -> None:
        async with Client(create_server()) as original:
            baseline = {t.name: t for t in await original.list_tools()}
        async with Client(create_server(instrumentation_jobs=task)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {*baseline, "host_emulator_instrumentation"}
            assert all(tools[name] == baseline[name] for name in baseline)
            tool = tools["host_emulator_instrumentation"]
            assert tool.output_schema == get_instrumentation_schema()
            Draft202012Validator.check_schema(tool.output_schema)
            assert tool.annotations is not None
            assert tool.annotations.model_dump(mode="json", by_alias=True)["destructiveHint"]
            plan = await client.call_tool(
                "host_emulator_instrumentation",
                {
                    "action": "plan",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "apk_handle": artifact,
                    "apk_sha256": sha,
                    "component": COMPONENT,
                },
            )
            assert not plan.is_error
            assert plan.structured_content["status"] == "planned"
            assert plan.structured_content["real_instrumentation_enabled"] is False
            Draft202012Validator(tool.output_schema).validate(plan.structured_content)
            blocked = await client.call_tool(
                "host_emulator_instrumentation",
                {
                    "action": "run",
                    "avd_name": NAME,
                    "avd_handle": handle,
                    "lifecycle_job_id": lid,
                    "apk_handle": artifact,
                    "apk_sha256": sha,
                    "component": COMPONENT,
                    "request_id": RUN_REQUEST,
                },
            )
            assert blocked.structured_content["status"] == "blocked"

    try:
        asyncio.run(verify())
    finally:
        live.shutdown()
    assert jobs.list_status(OWNER) == []

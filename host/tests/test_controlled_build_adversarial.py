"""H2.f adversarial single-checkout, replay and localhost Gradle fake cases."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastmcp import Client
from test_host_gradle_build_job import (
    ARTIFACT_OWNER,
    OWNER,
    REQUEST,
    REVISION,
    make,
    project,
)

from android_mcp_host.command_runner import RunResult
from android_mcp_host.controlled_build_jobs import ControlledBuildJobs
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.private_artifact_store import PrivateArtifactStore


def test_single_checkout_lock_denies_overlap_without_second_execution(tmp_path: Path) -> None:
    started = Event()
    release = Event()
    invocations: list[list[str]] = []

    def run(argv: Any, *other: Any) -> RunResult:
        invocations.append(list(argv))
        started.set()
        assert release.wait(10)
        return RunResult(0, "BUILD SUCCESSFUL", "", False)

    engine, _, records, _, _ = make(tmp_path, runner=run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(engine.submit, "lint_debug", REQUEST)
        try:
            assert started.wait(5)
            second = engine.submit("test_jvm", "independent-build-request")
            assert second["status"] in {"blocked", "in_progress"}
            assert len(invocations) == 1
            assert len(records.list_status(OWNER)) == 1
        finally:
            release.set()
        assert first.result(timeout=15)["state"] == "succeeded"


def test_replay_after_restart_returns_original_report_handle(tmp_path: Path) -> None:
    calls = [0]

    def run(*args: Any) -> RunResult:
        calls[0] += 1
        return RunResult(0, "success", "", False)

    builder, preflight, jobs, artifacts, root = make(tmp_path, runner=run)
    first = builder.submit("lint_debug", REQUEST)
    assert first["report_handle"].startswith("art_")
    reopened = ControlledBuildJobs(
        preflight=preflight,
        jobs=DurableJobStore(tmp_path / "private-jobs", lease_seconds=120),
        artifacts=PrivateArtifactStore(tmp_path / "private-artifacts"),
        root=root,
        approved_revision=REVISION,
        wrapper_sha256=preflight.digest,
        owner=OWNER,
        artifact_owner=ARTIFACT_OWNER,
        runner=run,
    )
    replay = reopened.submit("lint_debug", REQUEST)
    assert replay["state"] == "succeeded"
    assert replay["job_id"] == first["job_id"]
    assert replay["report_handle"] == first["report_handle"]
    assert replay["result_sha256"] == first["result_sha256"]
    assert calls == [1]
    report = json.loads(artifacts.read(ARTIFACT_OWNER, replay["report_handle"]))
    assert report["job_id"] == first["job_id"]


def test_stale_existing_apk_output_cannot_be_reported_as_fresh(tmp_path: Path) -> None:
    from test_host_gradle_build_job import fake_apk

    engine, _, _, _, root = make(tmp_path, runner=lambda *args: RunResult(0, "success", "", False))
    existing = root / "android/app/build/outputs/apk/debug/app-debug.apk"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(fake_apk())
    response = engine.submit("assemble_debug", REQUEST)
    assert response["status"] == "failed"
    assert response["errors"][0]["code"] == "OUTPUT_INVALID"
    assert response["apk_handle"] is None


def test_restricted_owner_and_quota_do_not_run_untrusted_jobs(tmp_path: Path) -> None:
    engine, _, _, _, root = make(tmp_path)
    for kind in (-1, float("nan"), float("inf"), True, 121.0):
        with pytest.raises(ValueError):
            ControlledBuildJobs(
                preflight=engine._preflight,
                jobs=engine._jobs,
                artifacts=engine._artifacts,
                root=root,
                approved_revision=REVISION,
                wrapper_sha256=engine._wrapper,
                owner=OWNER,
                artifact_owner=ARTIFACT_OWNER,
                timeout_s=kind,
            )
    with pytest.raises(ValueError):
        ControlledBuildJobs(
            preflight=engine._preflight,
            jobs=engine._jobs,
            artifacts=engine._artifacts,
            root=Path("relative"),
            approved_revision=REVISION,
            wrapper_sha256=engine._wrapper,
            owner=OWNER,
            artifact_owner=ARTIFACT_OWNER,
        )


def test_real_http_fake_gradle_is_offline_and_does_not_select_device(tmp_path: Path) -> None:
    source, digest = project(tmp_path / "source")
    gradlew = source / "android/gradlew"
    trace = tmp_path / "invocations.jsonl"
    gradlew.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{trace}"\necho "BUILD SUCCESSFUL"\n',
        encoding="utf-8",
    )
    gradlew.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    code = (
        "from pathlib import Path\n"
        "import sys\n"
        "from android_mcp_host.android_build_preflight import TASKS\n"
        "from android_mcp_host.controlled_build_jobs import ControlledBuildJobs\n"
        "from android_mcp_host.durable_jobs import DurableJobStore\n"
        "from android_mcp_host.private_artifact_store import PrivateArtifactStore\n"
        "from android_mcp_host.server import create_server\n"
        "root=Path(sys.argv[1]); digest=sys.argv[2]; private=Path(sys.argv[3])\n"
        "port=int(sys.argv[4]); private.mkdir(mode=0o700,exist_ok=True)\n"
        "class Fixed:\n"
        " def plan(self,a,v):\n"
        "  return {'status':'planned','action':a,'variant':v,'project_root':str(root),"
        "'expected_revision':'"
        + REVISION
        + "','observed_revision':'"
        + REVISION
        + "','wrapper_sha256':digest,'dirty':False,'execution_enabled':False,"
        "'tasks':list(TASKS[a])}\n"
        "builder=ControlledBuildJobs(preflight=Fixed(),jobs=DurableJobStore(private/'jobs'),"
        "artifacts=PrivateArtifactStore(private/'artifacts'),root=root,approved_revision='"
        + REVISION
        + "',wrapper_sha256=digest,owner='"
        + OWNER
        + "',artifact_owner='"
        + ARTIFACT_OWNER
        + "')\n"
        "create_server(build_jobs=builder).run(transport='http',host='127.0.0.1',port=port)\n"
    )
    env = os.environ.copy()
    env["TRACE_FILE"] = str(trace)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(source),
            digest,
            str(tmp_path / "private"),
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    async def check() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    result = await client.call_tool(
                        "host_gradle_build", {"action": "lint_debug", "request_id": REQUEST}
                    )
                    assert not result.is_error
                    assert result.structured_content["state"] == "succeeded"
                    second = await client.call_tool(
                        "host_gradle_build", {"action": "lint_debug", "request_id": REQUEST}
                    )
                    assert (
                        second.structured_content["job_id"] == result.structured_content["job_id"]
                    )
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"No local-only build result: {type(last).__name__}")

    try:
        asyncio.run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    recorded = trace.read_text(encoding="utf-8").splitlines()
    assert len(recorded) == 1
    assert "--offline" in recorded[0]
    assert "--no-daemon" in recorded[0]
    assert ":app:lintDebug" in recorded[0]
    assert "adb" not in recorded[0] and "install" not in recorded[0]


def test_cli_build_opt_in_rejects_partial_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import cli

    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs["host"] == "127.0.0.1"

    def factory(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub()

    with monkeypatch.context() as patch:
        patch.setattr(cli, "create_server", factory)
        patch.setattr(cli.platform, "system", lambda: "Linux")
        for args in (
            ["serve", "--controlled-build"],
            ["serve", "--build-timeout-seconds", "5"],
            ["serve", "--controlled-build", "--build-preflight"],
            ["serve", "--controlled-build", "--build-preflight", "--job-owner", OWNER],
        ):
            with pytest.raises(SystemExit) as result:
                cli.main(args)
            assert result.value.code == 2
        assert calls == []
        root = (tmp_path / "approved-source").resolve()
        flags = [
            "serve",
            "--controlled-build",
            "--build-preflight",
            "--build-root",
            str(root),
            "--build-approved-revision",
            REVISION,
            "--build-wrapper-sha256",
            "b" * 64,
            "--artifact-metadata",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--artifact-owner",
            ARTIFACT_OWNER,
            "--durable-job-status",
            "--job-root",
            str(tmp_path / "jobs"),
            "--job-owner",
            OWNER,
        ]
        assert cli.main(flags) == 0
        assert isinstance(calls[0]["build_jobs"], ControlledBuildJobs)

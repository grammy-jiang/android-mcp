"""H3.e durable replay, failure provenance and synthetic worker fault injections."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_instrumentation_jobs import (
    COMPONENT,
    INSTRUMENT_OWNER,
    RUN_REQUEST,
    setup_fixture,
    success,
)

from android_mcp_host.command_runner import RunResult
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_successful_replay_returns_same_report_without_running_again(tmp_path: Path) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        return success(*args)

    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    try:
        first = task.submit(
            "run",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert first["status"] == "ok" and first["passed"] == 2
        again = task.submit(
            "run",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert again["status"] == "ok" and again["state"] == "succeeded"
        assert again["job_id"] == first["job_id"]
        assert again["report_sha256"] == first["report_sha256"]
        assert again["report_handle"] == first["report_handle"]
        assert again["passed"] == 2 and again["failed"] == 0
        assert calls == [1]
        assert jobs.status(OWNER, first["job_id"])["job"]["attempts"] == 1
    finally:
        live.shutdown()


def test_private_report_read_failure_does_not_reexecute_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        return success(*args)

    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    try:
        original = task.submit(
            "run",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        with monkeypatch.context() as patch:
            patch.setattr(
                artifacts,
                "list_metadata",
                lambda *args: (_ for _ in ()).throw(ArtifactStoreError("STORAGE_FAILURE")),
            )
            response = task.submit(
                "run",
                NAME,
                avd,
                lifecycle_id,
                apk,
                sha,
                COMPONENT,
                request_id=RUN_REQUEST,
            )
        assert response["status"] == "ok"
        assert response["report_handle"] is None
        assert response["report_sha256"] == original["report_sha256"]
        assert calls == [1]
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    ("worker_output", "expected"),
    [
        (RunResult(0, "broken-json", "", False), "OUTPUT_INVALID"),
        (
            RunResult(0, '{"passed":2,"failed":0,"total":2,"synthetic":true}', "", True),
            "OUTPUT_INVALID",
        ),
        (
            RunResult(1, '{"passed":2,"failed":0,"total":2,"synthetic":true}', "", False),
            "TEST_FAILED",
        ),
        (
            RunResult(0, '{"passed":1,"failed":1,"total":2,"synthetic":true}', "", False),
            "TEST_FAILED",
        ),
        (
            RunResult(0, '{"passed":2,"failed":0,"total":2,"synthetic":true}', "WARNING", False),
            "TEST_FAILED",
        ),
    ],
)
def test_untrusted_runner_output_never_claims_success(
    tmp_path: Path,
    worker_output: RunResult,
    expected: str,
) -> None:
    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=lambda *args: worker_output,
    )
    try:
        response = task.submit(
            "run",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert response["status"] == "failed"
        assert response["errors"][0]["code"] == expected
        assert response["job_id"] is not None
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "failed"
        assert "WARNING" not in json.dumps(response)
    finally:
        live.shutdown()


def test_failed_test_replay_never_becomes_success(tmp_path: Path) -> None:
    calls = [0]

    def failed(*args: Any) -> RunResult:
        calls[0] += 1
        return RunResult(1, '{"passed":0,"failed":1,"total":1,"synthetic":true}', "", False)

    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=failed,
    )
    try:
        first = task.submit(
            "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
        )
        replay = task.submit(
            "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert first["status"] == "failed" and replay["status"] == "failed"
        assert replay["job_id"] == first["job_id"]
        assert calls == [1]
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "raised", [OSError("secret"), ValueError("secret"), RuntimeError("secret"), TypeError("secret")]
)
def test_unexpected_fake_runner_failure_is_uncertain_not_replayed(
    tmp_path: Path,
    raised: Exception,
) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        raise raised

    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    try:
        response = task.submit(
            "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "RUNNER_FAILED"
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
        assert "secret" not in json.dumps(response)
        assert (
            task.submit(
                "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
            )["status"]
            == "uncertain"
        )
        assert calls == [1]
    finally:
        live.shutdown()


def test_artifact_storage_denial_after_test_is_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                artifacts,
                "put",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    ArtifactStoreError("PRIVATE PATH FAILURE")
                ),
            )
            response = task.submit(
                "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
            )
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "RUNNER_FAILED"
        assert response["report_handle"] is None
        assert "PRIVATE" not in json.dumps(response)
    finally:
        live.shutdown()


def test_failed_journal_finalization_does_not_claim_report_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "complete",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
            )
            response = task.submit(
                "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
            )
        assert response["status"] == "uncertain"
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_cancel_failure_after_timeout_is_still_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=lambda *args: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["fixture-instrumentation"], 0.01)
        ),
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "cancel",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
            )
            response = task.submit(
                "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
            )
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "TIMEOUT"
        assert response["job_id"] is not None
    finally:
        live.shutdown()


def test_stale_ledger_error_and_cross_job_fence_block_new_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "lookup_request",
                lambda *args: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
            )
            denied = task.submit(
                "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
            )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        prior = jobs.prepare(OWNER, "unrelated-host-work", "a" * 64, identity=avd, authorized=True)
        jobs.queue(OWNER, prior["job_id"], identity=avd, authorized=True)
        jobs.claim(OWNER, prior["job_id"], "other-host-worker", avd, authorized=True)
        fenced = task.submit(
            "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert fenced["status"] == "blocked"
        assert fenced["errors"][0]["code"] == "RECOVERY_REQUIRED"
    finally:
        live.shutdown()


def test_emulator_exit_during_instrumentation_invalidates_successful_fixture_output(
    tmp_path: Path,
) -> None:
    closure: dict[str, Any] = {}

    def runner(*args: Any) -> RunResult:
        closure["lifecycle"].shutdown()
        return success(*args)

    task, live, jobs, artifacts, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=runner,
    )
    closure["lifecycle"] = live
    try:
        response = task.submit(
            "run",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
        )
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "UNVERIFIED_EMULATOR"
        assert response["report_handle"] is None
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
        assert any(record["handle"] == apk for record in artifacts.list_metadata(INSTRUMENT_OWNER))
    finally:
        live.shutdown()

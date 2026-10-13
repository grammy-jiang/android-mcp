"""H3.e cancellation is bound to exact synthetic test plan and owner."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_instrumentation_jobs import (
    COMPONENT,
    RUN_REQUEST,
    setup_fixture,
    success,
)

from android_mcp_host.durable_job_support import JobStoreError


def test_timed_out_synthetic_job_cancels_only_its_own_record(tmp_path: Path) -> None:
    def worker(*args: Any) -> Any:
        raise subprocess.TimeoutExpired(["fixture-instrumentation"], 0.01)

    task, live, jobs, store, avd, lifecycle_id, apk, sha = setup_fixture(tmp_path, runner=worker)
    try:
        run = task.submit(
            "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert run["status"] == "uncertain"
        cancel = task.submit(
            "cancel",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
            job_id=run["job_id"],
        )
        assert cancel["status"] == "uncertain"
        assert cancel["job_id"] == run["job_id"]
        assert jobs.status(OWNER, run["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_cancellation_cannot_target_lifecycle_job_id(tmp_path: Path) -> None:
    task, live, jobs, store, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        denied = task.submit(
            "cancel",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
            job_id=lifecycle_id,
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert jobs.status(OWNER, lifecycle_id)["job"]["state"] == "running"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_wrong_plan_never_cancels_synthetic_test(tmp_path: Path) -> None:
    task, live, jobs, store, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        info = live.provisioner.verify_owned(NAME, avd)
        assert info is not None
        digest = task._digest(info, lifecycle_id, apk, sha, COMPONENT)
        previous = jobs.prepare(
            OWNER,
            RUN_REQUEST,
            digest,
            identity=avd,
            authorized=True,
        )
        jobs.queue(OWNER, previous["job_id"], identity=avd, authorized=True)
        jobs.claim(OWNER, previous["job_id"], "h3e-fixture-worker", avd, authorized=True)
        denied = task.submit(
            "cancel",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            "org.example.synthetic.test/androidx.test.runner.DifferentRunner",
            request_id=RUN_REQUEST,
            job_id=previous["job_id"],
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert jobs.status(OWNER, previous["job_id"])["job"]["state"] == "running"
        correct = task.submit(
            "cancel",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
            job_id=previous["job_id"],
        )
        assert correct["status"] == "uncertain"
        assert jobs.status(OWNER, previous["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_finished_success_cannot_be_cancelled(tmp_path: Path) -> None:
    task, live, jobs, store, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        done = task.submit(
            "run", NAME, avd, lifecycle_id, apk, sha, COMPONENT, request_id=RUN_REQUEST
        )
        assert done["status"] == "ok"
        denied = task.submit(
            "cancel",
            NAME,
            avd,
            lifecycle_id,
            apk,
            sha,
            COMPONENT,
            request_id=RUN_REQUEST,
            job_id=done["job_id"],
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert jobs.status(OWNER, done["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


def test_cancel_rejects_invalid_job_id_before_private_store_write(tmp_path: Path) -> None:
    task, live, jobs, store, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        for invalid in (None, "", "bad/job", "job_" + "x" * 31):
            denied = task.submit(
                "cancel",
                NAME,
                avd,
                lifecycle_id,
                apk,
                sha,
                COMPONENT,
                request_id=RUN_REQUEST,
                job_id=invalid,
            )
            assert denied["status"] == "blocked"
            assert denied["errors"][0]["code"] == "INVALID_INPUT"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_cancel_journal_storage_error_is_uncertain_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, live, jobs, store, avd, lifecycle_id, apk, sha = setup_fixture(
        tmp_path,
        runner=success,
    )
    try:
        info = live.provisioner.verify_owned(NAME, avd)
        assert info is not None
        digest = task._digest(info, lifecycle_id, apk, sha, COMPONENT)
        previous = jobs.prepare(OWNER, RUN_REQUEST, digest, identity=avd, authorized=True)
        jobs.queue(OWNER, previous["job_id"], identity=avd, authorized=True)
        jobs.claim(OWNER, previous["job_id"], "h3e-fixture-worker", avd, authorized=True)
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "cancel",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
            )
            response = task.submit(
                "cancel",
                NAME,
                avd,
                lifecycle_id,
                apk,
                sha,
                COMPONENT,
                request_id=RUN_REQUEST,
                job_id=previous["job_id"],
            )
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert jobs.status(OWNER, previous["job_id"])["job"]["state"] == "running"
    finally:
        live.shutdown()

"""H3.f cancellation cannot cancel another Host job or silently retry effects."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_debug_deployment import (
    PACKAGE,
    REQ,
    fake_result,
    invoke,
    setup_deploy,
)

from android_mcp_host.command_runner import RunResult
from android_mcp_host.durable_job_support import JobStoreError


def cancel(
    engine: Any,
    handle: str,
    lid: str,
    apk: str,
    sha: str,
    *,
    request: str = REQ,
    job_id: str | None = None,
    original_action: str = "install",
    install_report: str | None = None,
) -> dict[str, Any]:
    return engine.submit(
        "cancel",
        NAME,
        handle,
        lid,
        apk,
        sha,
        PACKAGE,
        request_id=request,
        job_id=job_id,
        original_action=original_action,
        install_report_handle=install_report,
    )


def test_timed_out_install_can_cancel_only_its_own_plan(tmp_path: Path) -> None:
    def timeout(*args: Any) -> RunResult:
        raise subprocess.TimeoutExpired(["fixture-debug-deploy"], 0.01)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=timeout)
    try:
        uncertain = invoke(deploy, "install", handle, lid, apk, sha)
        assert uncertain["status"] == "uncertain"
        result = cancel(deploy, handle, lid, apk, sha, job_id=uncertain["job_id"])
        assert result["status"] == "uncertain"
        assert result["job_id"] == uncertain["job_id"]
        assert jobs.status(OWNER, uncertain["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_cannot_cancel_an_active_lifecycle_worker(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        denied = cancel(deploy, handle, lid, apk, sha, job_id=lid)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert jobs.status(OWNER, lid)["job"]["state"] == "running"
    finally:
        live.shutdown()


def test_cannot_cancel_finished_synthetic_install(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        done = invoke(deploy, "install", handle, lid, apk, sha)
        assert done["status"] == "simulated"
        denied = cancel(deploy, handle, lid, apk, sha, job_id=done["job_id"])
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert jobs.status(OWNER, done["job_id"])["job"]["state"] == "succeeded"
    finally:
        live.shutdown()


def test_cancel_request_plan_digest_binds_exact_action_and_report(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        info = live.provisioner.verify_owned(NAME, handle)
        assert info is not None
        digest = deploy._digest("install", info, lid, apk, sha, PACKAGE, None)
        prepared = jobs.prepare(OWNER, REQ, digest, identity=handle, authorized=True)
        jobs.queue(OWNER, prepared["job_id"], identity=handle, authorized=True)
        jobs.claim(OWNER, prepared["job_id"], "synthetic-debug-worker", handle, authorized=True)
        denied = cancel(
            deploy, handle, lid, apk, sha, job_id=prepared["job_id"], original_action="launch"
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
        assert jobs.status(OWNER, prepared["job_id"])["job"]["state"] == "running"
        permitted = cancel(deploy, handle, lid, apk, sha, job_id=prepared["job_id"])
        assert permitted["status"] == "uncertain"
        assert jobs.status(OWNER, prepared["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_wrong_idempotency_key_job_or_original_action_is_denied(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        info = live.provisioner.verify_owned(NAME, handle)
        assert info is not None
        digest = deploy._digest("install", info, lid, apk, sha, PACKAGE, None)
        prepared = jobs.prepare(OWNER, REQ, digest, identity=handle, authorized=True)
        jobs.queue(OWNER, prepared["job_id"], identity=handle, authorized=True)
        for request, job, action in (
            ("wrong-request-key", prepared["job_id"], "install"),
            (REQ, "job_" + "z" * 32, "install"),
            (REQ, prepared["job_id"], "connect-usb"),
            (REQ, prepared["job_id"], ""),
        ):
            denied = cancel(
                deploy, handle, lid, apk, sha, request=request, job_id=job, original_action=action
            )
            assert denied["status"] == "blocked"
        assert jobs.status(OWNER, prepared["job_id"])["job"]["state"] == "queued"
    finally:
        live.shutdown()


def test_cancel_storage_failure_is_uncertain_not_mutation_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        info = live.provisioner.verify_owned(NAME, handle)
        assert info is not None
        digest = deploy._digest("install", info, lid, apk, sha, PACKAGE, None)
        prepared = jobs.prepare(OWNER, REQ, digest, identity=handle, authorized=True)
        jobs.queue(OWNER, prepared["job_id"], identity=handle, authorized=True)
        jobs.claim(OWNER, prepared["job_id"], "synthetic-debug-worker", handle, authorized=True)
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "cancel",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
            )
            denied = cancel(deploy, handle, lid, apk, sha, job_id=prepared["job_id"])
        assert denied["status"] == "uncertain"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert jobs.status(OWNER, prepared["job_id"])["job"]["state"] == "running"
    finally:
        live.shutdown()


def test_cancel_during_blocked_synthetic_install_never_claims_success(tmp_path: Path) -> None:
    entered = Event()
    release = Event()
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        entered.set()
        assert release.wait(8)
        return fake_result(*args)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=runner)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, deploy, "install", handle, lid, apk, sha)
        try:
            assert entered.wait(4)
            running = next(
                row
                for row in jobs.list_status(OWNER)
                if row["job_id"] != lid and row["state"] == "running"
            )
            cancelled = cancel(deploy, handle, lid, apk, sha, job_id=running["job_id"])
            assert cancelled["status"] == "uncertain"
            assert jobs.status(OWNER, running["job_id"])["job"]["state"] == "uncertain"
        finally:
            release.set()
        result = first.result(timeout=15)
        assert result["status"] == "uncertain"
        assert result["report_handle"] is None
        assert calls == [1]
        assert not deploy._installed
    live.shutdown()


def test_production_plan_only_backend_denies_cancel_without_dispatch(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=None,
        running=False,
    )
    try:
        response = cancel(deploy, handle, lid, apk, sha, job_id="job_" + "x" * 32)
        assert response["status"] == "blocked"
        assert response["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert jobs.list_status(OWNER) == []
    finally:
        live.shutdown()

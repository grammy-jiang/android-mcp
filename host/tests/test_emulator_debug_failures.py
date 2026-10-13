"""H3.f durable debug deployment failure and idempotency invariants."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_avd_provisioning import NAME, OWNER
from test_emulator_debug_deployment import (
    ARTIFACT_OWNER,
    PACKAGE,
    REQ,
    fake_result,
    fixture_apk,
    invoke,
    setup_deploy,
)

from android_mcp_host.command_runner import RunResult
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


@pytest.mark.parametrize("timeout", [-1, 0, 11, True, "10", float("nan"), float("inf")])
def test_invalid_time_budget_denied_at_trusted_composition(
    tmp_path: Path,
    timeout: Any,
) -> None:
    from android_mcp_host.emulator_debug_deployment import DebugDeployment

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        with pytest.raises(ValueError, match="deadline"):
            DebugDeployment(
                live.provisioner,
                live,
                jobs,
                artifacts,
                owner=OWNER,
                artifact_owner=ARTIFACT_OWNER,
                expected_package=PACKAGE,
                timeout_s=timeout,
            )
    finally:
        live.shutdown()


def test_wrong_owner_or_wrong_package_config_is_rejected(tmp_path: Path) -> None:
    from android_mcp_host.emulator_debug_deployment import DebugDeployment

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        running=False,
    )
    try:
        for owner, art_owner, package in (
            ("foreign-owner", ARTIFACT_OWNER, PACKAGE),
            (OWNER, "not/valid", PACKAGE),
            (OWNER, ARTIFACT_OWNER, "com.someone.production"),
            (OWNER, ARTIFACT_OWNER, "invalid-package"),
        ):
            with pytest.raises(ValueError):
                DebugDeployment(
                    live.provisioner,
                    live,
                    jobs,
                    artifacts,
                    owner=owner,
                    artifact_owner=art_owner,
                    expected_package=package,
                )
    finally:
        live.shutdown()


def test_no_real_executor_even_when_fake_private_apk_is_valid(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=None,
        running=True,
    )
    try:
        assert invoke(deploy, "plan", handle, lid, apk, sha)["status"] == "planned"
        outcome = invoke(deploy, "install", handle, lid, apk, sha)
        assert outcome["status"] == "blocked"
        assert outcome["errors"][0]["code"] == "EXECUTION_DISABLED"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_wrong_private_artifact_mime_or_expired_handle_denied(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        content = fixture_apk(tmp_path)
        unrelated = artifacts.put(ARTIFACT_OWNER, content, mime_type="application/octet-stream")
        blocked = invoke(deploy, "install", handle, lid, unrelated["handle"], sha)
        assert blocked["status"] == "blocked"
        assert blocked["errors"][0]["code"] == "BAD_APK"
        assert artifacts.revoke(ARTIFACT_OWNER, apk) is True
        revoked = invoke(deploy, "install", handle, lid, apk, sha)
        assert revoked["status"] == "blocked"
        assert revoked["errors"][0]["code"] == "BAD_APK"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_unsupported_api_denied_by_fake_apk_gate(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        current = live.provisioner.verify_owned(NAME, handle)
        assert current is not None
        out_of_range = {**current, "api": 23}
        assert deploy._apk(apk, sha, out_of_range) is False
    finally:
        live.shutdown()


def test_invalid_action_request_and_absolute_host_path_denied(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        for action, request in (
            ("adb install", REQ),
            ("--unsafe", REQ),
            ("install", ""),
            ("install", "bad/request"),
            ("install", "x" * 200),
        ):
            denied = invoke(deploy, action, handle, lid, apk, sha, request=request)
            assert denied["status"] == "blocked"
        denied_path = invoke(deploy, "install", handle, lid, "/tmp/fake.apk", sha)
        assert denied_path["status"] == "blocked"
        assert denied_path["errors"][0]["code"] == "BAD_APK"
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "result",
    [
        RunResult(0, "garbage", "", False),
        RunResult(0, "{}", "", False),
        RunResult(
            0,
            json.dumps(
                {
                    "synthetic": True,
                    "action": "install",
                    "avd": NAME,
                    "package": PACKAGE,
                    "success": True,
                }
            ),
            "",
            True,
        ),
        RunResult(
            1,
            json.dumps(
                {
                    "synthetic": True,
                    "action": "install",
                    "avd": NAME,
                    "package": PACKAGE,
                    "success": True,
                }
            ),
            "",
            False,
        ),
        RunResult(
            0,
            json.dumps(
                {
                    "synthetic": True,
                    "action": "install",
                    "avd": NAME,
                    "package": PACKAGE,
                    "success": False,
                }
            ),
            "",
            False,
        ),
        RunResult(
            0,
            json.dumps(
                {
                    "synthetic": True,
                    "action": "install",
                    "avd": NAME,
                    "package": PACKAGE,
                    "success": True,
                }
            ),
            "secret stderr",
            False,
        ),
        RunResult(
            False,
            json.dumps(
                {
                    "synthetic": True,
                    "action": "install",
                    "avd": NAME,
                    "package": PACKAGE,
                    "success": True,
                }
            ),
            "",
            False,
        ),
    ],
)
def test_failed_or_malformed_fake_runner_never_reports_real_install(
    tmp_path: Path,
    result: RunResult,
) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=lambda *args: result,
    )
    try:
        failure = invoke(deploy, "install", handle, lid, apk, sha)
        assert failure["status"] == "failed"
        assert failure["errors"][0]["code"] in {"OUTPUT_INVALID", "FIXTURE_FAILED"}
        assert failure["install_state"] == "unknown"
        assert failure["report_handle"] is None
        assert jobs.status(OWNER, failure["job_id"])["job"]["state"] == "failed"
        assert "secret stderr" not in json.dumps(failure)
    finally:
        live.shutdown()


@pytest.mark.parametrize(
    "raised",
    [
        OSError("DO_NOT_LOG_SECRET"),
        ValueError("DO_NOT_LOG_SECRET"),
        RuntimeError("DO_NOT_LOG_SECRET"),
        TypeError("DO_NOT_LOG_SECRET"),
    ],
)
def test_runner_crash_is_uncertain_and_no_blind_reexecution(
    tmp_path: Path,
    raised: Exception,
) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        raise raised

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=runner,
    )
    try:
        uncertain = invoke(deploy, "install", handle, lid, apk, sha)
        assert uncertain["status"] == "uncertain"
        assert uncertain["errors"][0]["code"] == "RUNNER_FAILED"
        assert jobs.status(OWNER, uncertain["job_id"])["job"]["state"] == "uncertain"
        assert invoke(deploy, "install", handle, lid, apk, sha)["status"] == "uncertain"
        assert calls == [1]
        assert "DO_NOT_LOG_SECRET" not in json.dumps(uncertain)
    finally:
        live.shutdown()


def test_job_store_failure_before_claim_never_invokes_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        return fake_result(*args)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=runner)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "lookup_request",
                lambda *args: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
            )
            denied = invoke(deploy, "install", handle, lid, apk, sha)
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        assert calls == [0]
        assert len(jobs.list_status(OWNER)) == 1
    finally:
        live.shutdown()


def test_lifecycle_exit_during_fake_install_cannot_confirm_install(tmp_path: Path) -> None:
    state: dict[str, Any] = {}

    def runner(*args: Any) -> RunResult:
        state["lifecycle"].shutdown()
        return fake_result(*args)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=runner)
    state["lifecycle"] = live
    try:
        response = invoke(deploy, "install", handle, lid, apk, sha)
        assert response["status"] == "uncertain"
        assert response["errors"][0]["code"] == "UNVERIFIED_TARGET"
        assert response["report_handle"] is None
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_private_report_put_failure_cannot_claim_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                artifacts,
                "put",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    ArtifactStoreError("STORAGE_FAILURE")
                ),
            )
            result = invoke(deploy, "install", handle, lid, apk, sha)
        assert result["status"] == "uncertain"
        assert result["errors"][0]["code"] == "RUNNER_FAILED"
        assert result["report_handle"] is None
        assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"
    finally:
        live.shutdown()


def test_post_execution_job_commit_failure_does_not_report_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                jobs,
                "complete",
                lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
            )
            response = invoke(deploy, "install", handle, lid, apk, sha)
        assert response["status"] == "uncertain"
        assert jobs.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
        assert response["report_handle"] is None
    finally:
        live.shutdown()


def test_finished_install_replay_is_historical_without_rerun(tmp_path: Path) -> None:
    calls = [0]

    def runner(*args: Any) -> RunResult:
        calls[0] += 1
        return fake_result(*args)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path, runner=runner)
    try:
        first = invoke(deploy, "install", handle, lid, apk, sha)
        replay = invoke(deploy, "install", handle, lid, apk, sha)
        assert replay["status"] == "simulated"
        assert replay["job_id"] == first["job_id"]
        assert replay["report_handle"] == first["report_handle"]
        assert replay["report_sha256"] == first["report_sha256"]
        assert replay["install_state"] == "unknown"  # historical, not active proof
        assert replay["apk_sha256"] == sha
        assert replay["package_id"] == PACKAGE
        assert calls == [1]
    finally:
        live.shutdown()


def test_revoked_apk_during_fake_operation_cannot_be_confirmed_installed(
    tmp_path: Path,
) -> None:
    records: dict[str, Any] = {}

    def runner(*args: Any) -> RunResult:
        assert records["artifacts"].revoke(ARTIFACT_OWNER, records["apk"]) is True
        return fake_result(*args)

    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(
        tmp_path,
        runner=runner,
    )
    records.update({"artifacts": artifacts, "apk": apk})
    try:
        attempted = invoke(deploy, "install", handle, lid, apk, sha)
        assert attempted["status"] == "uncertain"
        assert attempted["errors"][0]["code"] == "BAD_APK"
        assert attempted["report_handle"] is None
        assert jobs.status(OWNER, attempted["job_id"])["job"]["state"] == "uncertain"
        assert not deploy._installed
    finally:
        live.shutdown()


def test_revoked_owned_install_receipt_blocks_later_synthetic_launch(tmp_path: Path) -> None:
    deploy, live, jobs, artifacts, handle, lid, apk, sha = setup_deploy(tmp_path)
    try:
        original = invoke(deploy, "install", handle, lid, apk, sha)
        assert original["status"] == "simulated"
        receipt = original["report_handle"]
        assert artifacts.revoke(ARTIFACT_OWNER, receipt) is True
        denied = invoke(
            deploy,
            "launch",
            handle,
            lid,
            apk,
            sha,
            install_report=receipt,
            request="launch-with-revoked-receipt",
        )
        assert denied["status"] == "blocked"
        assert denied["errors"][0]["code"] == "NOT_INSTALLED"
        assert len(jobs.list_status(OWNER)) == 2
    finally:
        live.shutdown()

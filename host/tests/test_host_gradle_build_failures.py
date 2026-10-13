"""Adversarial H2.f tests for executable pinning, storage, retries and processes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_host_gradle_build_job import (
    ARTIFACT_OWNER,
    OWNER,
    REQUEST,
    REVISION,
    make,
    project,
)

from android_mcp_host import cli
from android_mcp_host.command_runner import RunResult
from android_mcp_host.controlled_build_jobs import (
    ControlledBuildJobs,
    get_build_job_schema,
)
from android_mcp_host.durable_jobs import DurableJobStore
from android_mcp_host.private_artifact_support import ArtifactStoreError


@pytest.mark.parametrize(
    "change",
    [
        {"approved_revision": "a" * 39},
        {"approved_revision": None},
        {"wrapper_sha256": "B" * 64},
        {"owner": "bad/owner"},
        {"artifact_owner": "../other"},
        {"timeout_s": 0},
        {"timeout_s": 121},
        {"timeout_s": float("nan")},
        {"timeout_s": True},
    ],
)
def test_trusted_constructor_invalid_config_is_denied(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    builder, preflight, jobs, store, root = make(tmp_path)
    kwargs = {
        "preflight": preflight,
        "jobs": jobs,
        "artifacts": store,
        "root": root,
        "approved_revision": REVISION,
        "wrapper_sha256": preflight.digest,
        "owner": OWNER,
        "artifact_owner": ARTIFACT_OWNER,
        "timeout_s": 3.0,
    }
    kwargs.update(change)
    with pytest.raises(ValueError, match="Invalid"):
        ControlledBuildJobs(**kwargs)
    assert builder.submit("--device-install", "denied")["status"] == "blocked"


@pytest.mark.parametrize(
    "tamper",
    [
        "revision",
        "root",
        "digest",
        "dirty",
        "tasks",
        "execution",
        "action",
        "variant",
        "non_dictionary",
        "permission",
    ],
)
def test_mismatched_preflight_never_dispatches(
    tmp_path: Path, tamper: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []

    def denied(*args: Any) -> RunResult:
        calls.append(args)
        raise AssertionError("runner cannot execute")

    builder, preflight, jobs, _, _ = make(tmp_path, runner=denied)
    original = preflight.plan

    def plan(action: str, variant: str) -> Any:
        result = original(action, variant)
        match tamper:
            case "revision":
                result["observed_revision"] = "b" * 40
            case "root":
                result["project_root"] = "/tmp/other"
            case "digest":
                result["wrapper_sha256"] = "b" * 64
            case "dirty":
                result["dirty"] = True
            case "tasks":
                result["tasks"] = ["arbitraryShell"]
            case "execution":
                result["execution_enabled"] = True
            case "action":
                result["action"] = "installDebug"
            case "variant":
                result["variant"] = "release"
            case "non_dictionary":
                return None
            case "permission":
                raise PermissionError("PRIVATE")
        return result

    monkeypatch.setattr(preflight, "plan", plan)
    response = builder.submit("lint_debug", "fail-request")
    assert response["status"] == "blocked" and calls == []
    assert jobs.list_status(OWNER) == []


def test_untrusted_root_and_non_executable_wrapper_script_never_start(
    tmp_path: Path,
) -> None:
    def abort(*args: Any) -> RunResult:
        raise AssertionError("runner unexpectedly invoked")

    builder, _, _, _, root = make(tmp_path, runner=abort)
    script = root / "android/gradlew"
    script.chmod(0o600)
    assert builder.submit("test_jvm", "missing-exec")["status"] == "blocked"
    script.chmod(0o700)
    script.unlink()
    script.symlink_to("/bin/sh")
    assert builder.submit("test_jvm", "symlink-exec")["status"] == "blocked"
    script.unlink()
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o700)
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.jar"
    content = wrapper.read_bytes()
    wrapper.unlink()
    foreign = tmp_path / "other"
    foreign.write_bytes(content)
    wrapper.symlink_to(foreign)
    assert builder.submit("test_jvm", "symlink-jar")["status"] == "blocked"


def test_missing_and_symlinked_apk_output_fail_closed(tmp_path: Path) -> None:
    def no_output(*args: Any) -> RunResult:
        return RunResult(0, "build apparently succeeded", "", False)

    builder, _, jobs, store, root = make(tmp_path, runner=no_output)
    outside = tmp_path / "outside.apk"
    outside.write_bytes(b"PK\x03\x04invalid")
    output = root / "android/app/build/outputs/apk/debug/app-debug.apk"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.symlink_to(outside)
    result = builder.submit("assemble_debug", REQUEST)
    assert result["status"] == "failed" and result["errors"][0]["code"] == "OUTPUT_INVALID"
    assert store.list_metadata(ARTIFACT_OWNER) == []
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "failed"


def test_storage_failure_does_not_report_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder, _, jobs, store, _ = make(
        tmp_path, runner=lambda *args: RunResult(0, "success", "", False)
    )
    with monkeypatch.context() as scope:
        scope.setattr(
            store,
            "put",
            lambda *args, **kwargs: (_ for _ in ()).throw(ArtifactStoreError("QUOTA_EXCEEDED")),
        )
        result = builder.submit("lint_debug", REQUEST)
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "ARTIFACT_FAILED"
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "failed"


def test_failed_runner_never_retries_unknown_effect(tmp_path: Path) -> None:
    calls = [0]

    def crash(*args: Any) -> RunResult:
        calls[0] += 1
        raise OSError("SECRET crash after subprocess launch")

    builder, _, jobs, _, _ = make(tmp_path, runner=crash)
    first = builder.submit("test_jvm", REQUEST)
    assert first["status"] == "uncertain" and first["state"] == "uncertain"
    again = builder.submit("test_jvm", REQUEST)
    assert first["job_id"] == again["job_id"]
    assert calls == [1]
    assert jobs.status(OWNER, first["job_id"])["job"]["attempts"] == 1
    assert "SECRET" not in json.dumps(first)


def test_prepared_queued_running_and_cancelled_states_never_start_second_worker(
    tmp_path: Path,
) -> None:
    calls: list[Any] = []
    builder, _, jobs, _, _ = make(
        tmp_path, runner=lambda *args: calls.append(args) or RunResult(0, "", "", False)
    )
    plan = builder._approved
    assert plan("lint_debug", "debug") is True
    digest = hashlib.sha256(
        json.dumps(
            {
                "action": "lint_debug",
                "variant": "debug",
                "revision": REVISION,
                "wrapper": builder._wrapper,
            },
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    for state in ("queued", "running", "cancelled"):
        key = f"test-state-{state}"
        record = jobs.prepare(OWNER, key, digest, identity=REVISION, authorized=True)
        if state in {"queued", "running", "cancelled"}:
            jobs.queue(OWNER, record["job_id"], identity=REVISION, authorized=True)
        if state in {"running", "cancelled"}:
            jobs.claim(
                OWNER,
                record["job_id"],
                "fixture-worker",
                REVISION,
                authorized=True,
            )
        if state == "cancelled":
            # Running cancellation is intentionally uncertain, never successful cancellation.
            jobs.cancel(OWNER, record["job_id"], identity=REVISION, authorized=True)
        reply = builder.submit("lint_debug", key)
        assert reply["job_id"] == record["job_id"]
        assert reply["status"] in {"in_progress", "uncertain"}
    assert calls == []


def test_parallel_duplicate_submit_has_one_executor(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    counter = [0]
    lock = threading.Lock()

    def run(*args: Any) -> RunResult:
        with lock:
            counter[0] += 1
        entered.set()
        assert release.wait(3.0)
        return RunResult(0, "", "", False)

    builder, _, jobs, _, _ = make(tmp_path, runner=run, timeout_s=5.0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(builder.submit, "lint_debug", REQUEST)
        assert entered.wait(3.0)
        second = pool.submit(builder.submit, "lint_debug", REQUEST)
        observed = second.result(timeout=3)
        assert observed["status"] == "in_progress"
        release.set()
        final = first.result(timeout=3)
    assert final["status"] == "ok"
    assert final["job_id"] == observed["job_id"]
    assert counter == [1]
    assert jobs.status(OWNER, final["job_id"])["job"]["attempts"] == 1


def test_restart_expired_running_job_stays_uncertain_without_retry(tmp_path: Path) -> None:
    builder, preflight, jobs, store, root = make(
        tmp_path, runner=lambda *args: (_ for _ in ()).throw(AssertionError("never execute"))
    )
    digest = hashlib.sha256(
        json.dumps(
            {
                "action": "lint_debug",
                "variant": "debug",
                "revision": REVISION,
                "wrapper": preflight.digest,
            },
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    rec = jobs.prepare(OWNER, REQUEST, digest, identity=REVISION, authorized=True)
    jobs.queue(OWNER, rec["job_id"], identity=REVISION, authorized=True)
    jobs.claim(OWNER, rec["job_id"], "crashed-worker", REVISION, authorized=True)
    fresh = DurableJobStore(
        tmp_path / "private-jobs",
        clock=lambda: time.time() + 1000,
        lease_seconds=120,
    )
    assert fresh.status(OWNER, rec["job_id"])["job"]["state"] == "uncertain"
    restarted = ControlledBuildJobs(
        preflight=preflight,
        jobs=fresh,
        artifacts=store,
        root=root,
        approved_revision=REVISION,
        wrapper_sha256=preflight.digest,
        owner=OWNER,
        artifact_owner=ARTIFACT_OWNER,
        runner=lambda *args: (_ for _ in ()).throw(AssertionError("restart must never execute")),
    )
    assert restarted.submit("lint_debug", REQUEST)["state"] == "uncertain"
    assert fresh.status(OWNER, rec["job_id"])["job"]["attempts"] == 1


def test_bounded_default_gradle_runner_handles_cwd_and_timeout(tmp_path: Path) -> None:
    from android_mcp_host.controlled_build_jobs import _run_gradle

    executable = tmp_path / "fake-gradlew"
    executable.write_text("#!/bin/sh\npwd\nprintf 'done\\n'\n", encoding="utf-8")
    executable.chmod(0o700)
    result = _run_gradle([str(executable)], 2.0, 1024, tmp_path)
    assert result.returncode == 0 and result.truncated is False
    assert result.stdout.splitlines() == [str(tmp_path), "done"]
    executable.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        _run_gradle([str(executable)], 0.1, 1024, tmp_path)


def test_cli_controlled_build_default_denial_and_trusted_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, digest = project(tmp_path / "project")
    calls: list[dict[str, Any]] = []

    class Stub:
        def run(self, **kwargs: Any) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8765}

    with monkeypatch.context() as scoped:
        scoped.setattr(cli, "create_server", lambda **kwargs: calls.append(kwargs) or Stub())
        scoped.setattr(cli.platform, "system", lambda: "Linux")
        assert cli.main(["serve"]) == 0
        assert calls == [{}]
        calls.clear()
        for argv in (
            ["serve", "--controlled-build"],
            ["serve", "--build-timeout-seconds", "30"],
            ["serve", "--controlled-build", "--build-preflight"],
            ["serve", "--controlled-build", "--artifact-metadata"],
        ):
            with pytest.raises(SystemExit) as err:
                cli.main(argv)
            assert err.value.code == 2
            assert calls == []
        flags = [
            "serve",
            "--controlled-build",
            "--build-preflight",
            "--build-root",
            str(tmp_path / "project"),
            "--build-approved-revision",
            REVISION,
            "--build-wrapper-sha256",
            digest,
            "--artifact-metadata",
            "--artifact-root",
            str(tmp_path / "objects"),
            "--artifact-owner",
            ARTIFACT_OWNER,
            "--durable-job-status",
            "--job-root",
            str(tmp_path / "jobs"),
            "--job-owner",
            OWNER,
        ]
        assert cli.main(flags) == 0
        assert calls[0]["build_jobs"].submit("bad-task", "fake")["status"] == "blocked"
        assert calls[0]["durable_jobs"] is not None


def test_schema_non_object_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    import android_mcp_host.controlled_build_jobs as impl

    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-controlled-build-job.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(impl, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        get_build_job_schema()


def test_untrusted_root_and_missing_wrapper_branches(tmp_path: Path) -> None:
    from android_mcp_host.controlled_build_jobs import ControlledBuildJobs

    builder, preflight, jobs, store, root = make(tmp_path)
    linked = tmp_path / "linked-root"
    linked.symlink_to(root, target_is_directory=True)
    options = {
        "preflight": preflight,
        "jobs": jobs,
        "artifacts": store,
        "approved_revision": REVISION,
        "wrapper_sha256": preflight.digest,
        "owner": OWNER,
        "artifact_owner": ARTIFACT_OWNER,
    }
    assert (
        ControlledBuildJobs(root=linked, **options).submit("lint_debug", "linked")["status"]
        == "blocked"
    )
    absent = tmp_path / "absent-project"
    assert (
        ControlledBuildJobs(root=absent, **options).submit("lint_debug", "missing-root")["status"]
        == "blocked"
    )
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.jar"
    wrapper.unlink()
    assert builder.submit("lint_debug", "missing-wrapper")["status"] == "blocked"
    assert jobs.list_status(OWNER) == []


def test_invalid_request_ids_fail_before_any_job(tmp_path: Path) -> None:
    builder, _, jobs, _, _ = make(tmp_path)
    for value in (None, 123, "", "ab", "../../etc", "a" * 129):
        assert builder.submit("lint_debug", value)["errors"][0]["code"] == "INVALID_REQUEST"
    assert jobs.list_status(OWNER) == []


def test_corrupted_apk_output_fails_offline_validation(tmp_path: Path) -> None:
    def create_invalid(argv: Any, timeout: float, limit: int, cwd: Path) -> RunResult:
        apk = cwd / "app/build/outputs/apk/debug/app-debug.apk"
        apk.parent.mkdir(parents=True, exist_ok=True)
        apk.write_bytes(b"not a real zip archive")
        return RunResult(0, "fake build success", "", False)

    builder, _, jobs, store, _ = make(tmp_path, runner=create_invalid)
    result = builder.submit("assemble_debug", REQUEST)
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "OUTPUT_INVALID"
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "failed"
    assert store.list_metadata(ARTIFACT_OWNER) == []


def test_durable_completion_denial_remains_uncertain_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host.durable_job_support import JobStoreError

    builder, _, jobs, _, _ = make(tmp_path, runner=lambda *args: RunResult(0, "", "", False))
    with monkeypatch.context() as scope:
        scope.setattr(
            jobs,
            "complete",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
        )
        result = builder.submit("lint_debug", REQUEST)
    assert result["status"] == "uncertain"
    assert result["state"] == "uncertain"
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "uncertain"


@pytest.mark.parametrize("failure", ["timeout", "exception"])
def test_cancel_failure_is_generic_and_retry_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from android_mcp_host.durable_job_support import JobStoreError

    def failed(*args: Any) -> RunResult:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(["gradlew"], 0.1)
        raise OSError("SECRET")

    builder, _, jobs, _, _ = make(tmp_path, runner=failed)
    with monkeypatch.context() as scope:
        scope.setattr(
            jobs,
            "cancel",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
        )
        response = builder.submit("test_jvm", REQUEST)
    assert response["status"] == "uncertain"
    assert "SECRET" not in json.dumps(response)
    assert builder.submit("test_jvm", REQUEST)["status"] == "in_progress"

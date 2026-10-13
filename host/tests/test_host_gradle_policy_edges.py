"""H2.f explicit private file/lock faults and truth-preserving replay edges."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from test_host_gradle_build_job import (
    ARTIFACT_OWNER,
    OWNER,
    REQUEST,
    fake_apk,
    make,
)

from android_mcp_host.command_runner import RunResult
from android_mcp_host.controlled_build_support import checkout_lock, output_stamp, safe_build_file
from android_mcp_host.durable_job_support import JobStoreError
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_private_file_reader_is_regular_owned_no_follow_and_bounded(tmp_path: Path) -> None:
    ordinary = tmp_path / "ordinary"
    ordinary.write_bytes(b"safe")
    assert safe_build_file(ordinary, 4) == b"safe"
    assert safe_build_file(ordinary, 3) is None
    assert safe_build_file(tmp_path / "missing", 4) is None
    assert safe_build_file(tmp_path, 1000) is None
    alias = tmp_path / "alias"
    alias.symlink_to(ordinary)
    assert safe_build_file(alias, 100) is None
    hardlink = tmp_path / "hardlink"
    os.link(ordinary, hardlink)
    assert safe_build_file(hardlink, 100) is None
    ordinary.write_bytes(b"")
    assert safe_build_file(ordinary, 100) is None


def test_checkout_lock_refuses_parallel_open_and_insecure_file(tmp_path: Path) -> None:
    private = tmp_path / "job-dir"
    private.mkdir(mode=0o700)
    project = tmp_path / "project"
    project.mkdir()
    fd = checkout_lock(private, project)
    assert isinstance(fd, int)
    try:
        assert checkout_lock(private, project) is None
    finally:
        os.close(fd)
    second = checkout_lock(private, project)
    assert isinstance(second, int)
    os.close(second)
    path = next(private.glob("gradle-*.lock"))
    path.chmod(0o644)
    with pytest.raises(OSError):
        checkout_lock(private, project)
    path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"lock")
    path.symlink_to(outside)
    with pytest.raises(OSError):
        checkout_lock(private, project)


def test_output_stamp_rejects_nonregular_and_reports_changes(tmp_path: Path) -> None:
    assert output_stamp(tmp_path) is None
    output = tmp_path / "android/app/build/outputs/apk/debug/app-debug.apk"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"first")
    before = output_stamp(tmp_path)
    assert before is not None
    output.write_bytes(b"second")
    assert output_stamp(tmp_path) != before
    linked = tmp_path / "duplicate"
    os.link(output, linked)
    with pytest.raises(ValueError):
        output_stamp(tmp_path)
    linked.unlink()
    output.unlink()
    output.symlink_to(tmp_path / "nonexistent")
    with pytest.raises(ValueError):
        output_stamp(tmp_path)


def test_private_replay_ignores_unrelated_or_revoked_artifacts(tmp_path: Path) -> None:
    def synth_apk(argv: Any, seconds: float, limit: int, cwd: Path) -> RunResult:
        output = cwd / "app/build/outputs/apk/debug/app-debug.apk"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(fake_apk())
        return RunResult(0, "success", "", False)

    builder, _, _, store, _ = make(tmp_path, runner=synth_apk)
    store.put(ARTIFACT_OWNER, b"unrelated", mime_type="text/plain")
    initial = builder.submit("assemble_debug", REQUEST)
    assert initial["status"] == "ok"
    again = builder.submit("assemble_debug", REQUEST)
    assert again["report_handle"] == initial["report_handle"]
    assert again["apk_handle"] == initial["apk_handle"]

    assert store.revoke(ARTIFACT_OWNER, initial["apk_handle"]) is True
    no_apk = builder.submit("assemble_debug", REQUEST)
    assert no_apk["status"] == "ok" and no_apk["apk_handle"] is None
    assert no_apk["report_handle"] == initial["report_handle"]

    assert store.revoke(ARTIFACT_OWNER, initial["report_handle"]) is True
    no_report = builder.submit("assemble_debug", REQUEST)
    assert no_report["status"] == "ok" and no_report["report_handle"] is None
    assert no_report["result_sha256"] == initial["result_sha256"]


def test_private_replay_storage_fault_fails_closed_without_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executions = [0]

    def run(*args: Any) -> RunResult:
        executions[0] += 1
        return RunResult(0, "", "", False)

    builder, _, _, store, _ = make(tmp_path, runner=run)
    first = builder.submit("lint_debug", REQUEST)
    with monkeypatch.context() as patch:
        patch.setattr(
            store,
            "list_metadata",
            lambda owner: (_ for _ in ()).throw(ArtifactStoreError("STORAGE_FAILURE")),
        )
        replay = builder.submit("lint_debug", REQUEST)
    assert replay["job_id"] == first["job_id"]
    assert replay["report_handle"] is None
    assert replay["status"] == "ok"
    assert executions == [1]


def test_insecure_lock_and_stale_worker_failure_do_not_claim_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder, _, jobs, _, root = make(tmp_path, runner=lambda *args: RunResult(1, "", "", False))
    key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
    lock = jobs.private_root / ("gradle-" + key + ".lock")
    lock.write_bytes(b"")
    lock.chmod(0o644)
    blocked = builder.submit("lint_debug", REQUEST)
    assert blocked["status"] == "blocked" and blocked["errors"][0]["code"] == "JOB_UNAVAILABLE"
    lock.chmod(0o600)

    with monkeypatch.context() as patch:
        patch.setattr(
            jobs,
            "complete",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("STALE_WORKER")),
        )
        failed = builder.submit("lint_debug", "failed-finalization")
    assert failed["status"] == "uncertain"
    assert failed["errors"][0]["code"] == "JOB_UNAVAILABLE"


def test_busy_checkout_conflicting_idempotency_and_lookup_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = Event()
    release = Event()

    def waiting(*args: Any) -> RunResult:
        entered.set()
        assert release.wait(10)
        return RunResult(0, "", "", False)

    builder, _, jobs, _, _ = make(tmp_path, runner=waiting)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(builder.submit, "lint_debug", REQUEST)
        try:
            assert entered.wait(4)
            conflict = builder.submit("test_jvm", REQUEST)
            assert conflict["status"] == "blocked"
            assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"

            with monkeypatch.context() as patch:
                patch.setattr(
                    jobs,
                    "lookup_request",
                    lambda *args: (_ for _ in ()).throw(JobStoreError("STORAGE_FAILURE")),
                )
                denied = builder.submit("lint_debug", REQUEST)
            assert denied["status"] == "blocked"
            assert denied["errors"][0]["code"] == "JOB_UNAVAILABLE"
        finally:
            release.set()
        assert first.result(timeout=15)["status"] == "ok"


def test_conflicting_queue_transition_returns_authoritative_prior_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder, _, jobs, _, _ = make(
        tmp_path,
        runner=lambda *args: (_ for _ in ()).throw(AssertionError("Worker must not execute")),
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            jobs,
            "queue",
            lambda *args, **kwargs: (_ for _ in ()).throw(JobStoreError("INVALID_TRANSITION")),
        )
        result = builder.submit("lint_debug", REQUEST)
    assert result["status"] == "in_progress"
    assert result["state"] == "prepared"
    assert jobs.status(OWNER, result["job_id"])["job"]["state"] == "prepared"


def test_durable_request_lookup_invalid_replay_denials(tmp_path: Path) -> None:
    from android_mcp_host.durable_jobs import DurableJobStore

    store = DurableJobStore(tmp_path / "jobs")
    assert store.lookup_request(OWNER, REQUEST, "a" * 64, "fixture-id") is None
    for request, digest, identity, code in (
        ("bad", "x" * 64, "fixture", "INVALID_PLAN"),
        ("wrong!id", "a" * 64, "fixture", "INVALID_REQUEST"),
        (REQUEST, "a" * 64, "..bad", "INVALID_IDENTITY"),
    ):
        with pytest.raises(JobStoreError) as error:
            store.lookup_request(OWNER, request, digest, identity)
        assert error.value.code == code


def test_default_runner_uses_operator_private_gradle_home(tmp_path: Path) -> None:
    builder, _, jobs, _, root = make(tmp_path)
    script = root / "android/gradlew"
    report_path = tmp_path / "environment-report.txt"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n%s\\n" "$HOME" "$GRADLE_USER_HOME" > "{report_path}"\n'
        "echo 'synthetic lint success'\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    result = builder.submit("lint_debug", "private-home-test")
    assert result["status"] == "ok"
    saved = report_path.read_text(encoding="utf-8").splitlines()
    assert len(saved) == 2
    assert saved[0] == saved[1]
    assert saved[0].startswith(str(jobs.private_root))
    home = Path(saved[0])
    assert home.is_dir()
    assert home.stat().st_mode & 0o777 == 0o700


def test_cli_invalid_controlled_build_deadline_is_parser_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_host_gradle_build_job import REVISION, project

    from android_mcp_host import cli

    _, digest = project(tmp_path / "source")
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        flags = [
            "serve",
            "--controlled-build",
            "--build-preflight",
            "--build-root",
            str(tmp_path / "source"),
            "--build-approved-revision",
            REVISION,
            "--build-wrapper-sha256",
            digest,
            "--artifact-metadata",
            "--artifact-root",
            str(tmp_path / "private-artifacts"),
            "--artifact-owner",
            ARTIFACT_OWNER,
            "--durable-job-status",
            "--job-root",
            str(tmp_path / "private-jobs"),
            "--job-owner",
            OWNER,
        ]
        for value in ("0", "121", "nan", "inf"):
            with pytest.raises(SystemExit) as error:
                cli.main([*flags, "--build-timeout-seconds", value])
            assert error.value.code == 2
        assert not (tmp_path / "private-artifacts").exists()
        assert not (tmp_path / "private-jobs").exists()


def test_unfinished_or_uncertain_previous_job_blocks_new_request(
    tmp_path: Path,
) -> None:
    import hashlib
    import json

    from test_host_gradle_build_job import REVISION

    builder, preflight, records, _, _ = make(
        tmp_path, runner=lambda *args: RunResult(0, "safe", "", False)
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
    old = records.prepare(OWNER, "previous-job", digest, identity=REVISION, authorized=True)
    records.queue(OWNER, old["job_id"], identity=REVISION, authorized=True)
    records.claim(OWNER, old["job_id"], "crashed-gradle-worker", REVISION, authorized=True)
    new = builder.submit("test_jvm", "next-job")
    assert new["status"] == "blocked"
    assert new["errors"][0]["code"] == "RECOVERY_REQUIRED"
    assert len(records.list_status(OWNER)) == 1

    old_status = builder.submit("lint_debug", "previous-job")
    assert old_status["job_id"] == old["job_id"]
    assert old_status["state"] == "running"
    records.cancel(OWNER, old["job_id"], identity=REVISION, authorized=True)
    assert builder.submit("test_jvm", "next-job")["errors"][0]["code"] == "RECOVERY_REQUIRED"
    records.reconcile(
        OWNER,
        old["job_id"],
        identity=REVISION,
        authorized=True,
        evidence_digest="f" * 64,
        outcome="failed",
    )
    after = builder.submit("test_jvm", "next-job")
    assert after["state"] == "succeeded"

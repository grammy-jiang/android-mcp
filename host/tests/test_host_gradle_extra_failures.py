"""Additional cross-process H2.f denials and malformed worker boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_host_gradle_build_job import ARTIFACT_OWNER, OWNER, REQUEST, REVISION, make, project

from android_mcp_host import cli
from android_mcp_host.controlled_build_support import checkout_lock
from android_mcp_host.private_artifact_support import ArtifactStoreError


def test_separate_process_cannot_acquire_busy_checkout_file(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    project_root = tmp_path / "project"
    project_root.mkdir()
    fd = checkout_lock(private_root, project_root)
    assert fd is not None
    code = (
        "import sys,os\n"
        "from pathlib import Path\n"
        "from android_mcp_host.controlled_build_support import checkout_lock\n"
        "fd=checkout_lock(Path(sys.argv[1]),Path(sys.argv[2]))\n"
        "print('BUSY' if fd is None else 'INCORRECTLY_ACQUIRED')\n"
        "if fd is not None: os.close(fd)\n"
    )
    try:
        child = subprocess.run(
            [sys.executable, "-c", code, str(private_root), str(project_root)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "BUSY"
    finally:
        os.close(fd)


@pytest.mark.parametrize("return_value", [None, "ok", {"returncode": 0}, 17])
def test_malformed_runner_return_cannot_leave_silent_success(
    tmp_path: Path, return_value: Any
) -> None:
    builder, _, records, _, _ = make(tmp_path, runner=lambda *args: return_value)
    response = builder.submit("lint_debug", REQUEST)
    assert response["status"] == "uncertain"
    assert response["errors"][0]["code"] == "RUNNER_FAILED"
    assert response["job_id"] is not None
    assert records.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"


def test_private_gradle_home_creation_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from android_mcp_host import controlled_build_jobs

    builder, _, records, store, _ = make(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            controlled_build_jobs,
            "_private_directory",
            lambda *_: (_ for _ in ()).throw(ArtifactStoreError("UNTRUSTED_ROOT")),
        )
        response = builder.submit("lint_debug", REQUEST)
    assert response["status"] == "uncertain"
    assert response["errors"][0]["code"] == "RUNNER_FAILED"
    assert records.status(OWNER, response["job_id"])["job"]["state"] == "uncertain"
    assert store.list_metadata(ARTIFACT_OWNER) == []


def test_cli_unapproved_source_digest_fails_without_any_private_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, digest = project(tmp_path / "source")
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        common = [
            "serve",
            "--controlled-build",
            "--build-preflight",
            "--build-root",
            str(root),
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
        for key, value in (
            ("--build-approved-revision", "x" * 40),
            ("--build-wrapper-sha256", "X" * 64),
        ):
            args = common[:]
            args[args.index(key) + 1] = value
            with pytest.raises(SystemExit) as caught:
                cli.main(args)
            assert caught.value.code == 2
        assert not (tmp_path / "jobs").exists()
        assert not (tmp_path / "objects").exists()


def test_cli_relative_build_root_fail_closed_before_creating_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(cli.platform, "system", lambda: "Linux")
        with pytest.raises(SystemExit) as caught:
            cli.main(["serve", "--build-preflight", "--build-root", "relative/dir"])
        assert caught.value.code == 2

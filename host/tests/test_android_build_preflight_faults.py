"""H2.b adversarial static-source and read-only Git metadata cases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_android_build_preflight import (
    CHECKSUM,
    COMMIT,
    GRADLE_METADATA,
    GitRunner,
    Inventory,
    checked,
    code,
    make_project,
    service,
)

import android_mcp_host.android_build_preflight as bp
from android_mcp_host.command_runner import RunResult


def test_schema_loader_rejects_non_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name == "host-android-build-preflight.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(bp, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        bp.get_build_preflight_output_schema()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (GRADLE_METADATA.encode(), ("9.6.0", CHECKSUM)),
        (b"\xff\xfe\xfd", None),
        (b"garbage without equals", None),
        (GRADLE_METADATA.replace("retries=0", "retries=3").encode(), None),
        (
            GRADLE_METADATA.replace(
                "validateDistributionUrl=true", "validateDistributionUrl=false"
            ).encode(),
            None,
        ),
        (
            GRADLE_METADATA.replace(
                "distributionSha256Sum=" + CHECKSUM, "distributionSha256Sum=short"
            ).encode(),
            None,
        ),
        (GRADLE_METADATA.replace("gradle-9.6.0-bin.zip", "gradle-10.0-bin.zip").encode(), None),
        (GRADLE_METADATA.replace("https\\://", "http\\://").encode(), None),
        (GRADLE_METADATA.encode() + b"retries=0\n", None),
        (b"# commented\n! ignored\n\n" + GRADLE_METADATA.encode(), ("9.6.0", CHECKSUM)),
    ],
)
def test_wrapper_properties_are_strict_pinned_metadata(
    content: bytes, expected: tuple[str, str] | None
) -> None:
    assert bp._wrapper_metadata(content) == expected


@pytest.mark.parametrize(
    ("app", "settings", "valid"),
    [
        (
            b'plugins { id("com.android.application") version "9.4.0" }\n'
            b"android { compileSdk = 36\nsourceCompatibility = JavaVersion.VERSION_17 }\n",
            b'include(":app")\nenableAndroidApp\n',
            True,
        ),
        (b"\xff", b'include(":app")\nenableAndroidApp', False),
        (
            b'plugins { id("com.android.application") version "9.3.0" }',
            b'include(":app")\nenableAndroidApp',
            False,
        ),
        (
            b'plugins { id("com.android.application") version "9.4.0" }\ncompileSdk = 35',
            b'include(":app")\nenableAndroidApp',
            False,
        ),
        (
            b'plugins { id("com.android.application") version "9.4.0" }\ncompileSdk = 36',
            b'include(":app")\nenableAndroidApp',
            False,
        ),
        (
            (
                b'plugins { id("com.android.application") version "9.4.0" }\n'
                b"compileSdk = 36\nsourceCompatibility = JavaVersion.VERSION_17"
            ),
            b'include(":native-protocol")\nenableAndroidApp',
            False,
        ),
        (
            (
                b'plugins { id("com.android.application") version "9.4.0" }\n'
                b"compileSdk = 36\nsourceCompatibility = JavaVersion.VERSION_17"
            ),
            b'include(":app")',
            False,
        ),
        (
            (
                b'plugins { id("com.android.application") version "9.4.0" }\n'
                b"compileSdk = 36\nsourceCompatibility = JavaVersion.VERSION_17"
            ),
            b"\xff",
            False,
        ),
    ],
)
def test_static_app_metadata_must_be_pinned(app: bytes, settings: bytes, valid: bool) -> None:
    assert bp._build_metadata(app, settings) is valid


def test_path_escape_is_rejected_before_reading_any_other_file(tmp_path: Path) -> None:
    root, _ = make_project(tmp_path)
    outside = tmp_path / "private-credentials.txt"
    outside.write_text("SECRET_012345", encoding="utf-8")
    assert bp._static_file(root, "../private-credentials.txt") is None
    assert bp._static_file(root, "../../private-credentials.txt") is None
    assert bp._static_file(root, str(outside)) is None
    assert bp._static_file(root, "") is None


def test_static_file_symlink_missing_empty_too_large_denied(tmp_path: Path) -> None:
    root, _ = make_project(tmp_path)
    path = root / "android/app/build.gradle.kts"
    assert bp._static_file(root, "android/app/build.gradle.kts") == path.read_bytes()
    assert bp._static_file(root, "missing") is None
    assert bp._static_file(root, "android") is None
    path.write_bytes(b"")
    assert bp._static_file(root, "android/app/build.gradle.kts") is None
    path.write_bytes(b"x" * (bp.MAX_FILE_BYTES + 1))
    assert bp._static_file(root, "android/app/build.gradle.kts") is None
    path.unlink()
    outside = tmp_path / "outside"
    outside.write_text("PRIVATE", encoding="utf-8")
    path.symlink_to(outside)
    assert bp._static_file(root, "android/app/build.gradle.kts") is None


def test_static_file_read_faults_are_canonicalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = make_project(tmp_path)
    path = root / "android/app/build.gradle.kts"
    stat_method = Path.stat
    reader = Path.read_bytes

    def bad_read(self: Path) -> bytes:
        if self == path:
            raise OSError("device username in private path")
        return reader(self)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "read_bytes", bad_read)
        assert bp._static_file(root, "android/app/build.gradle.kts") is None

    def stale_read(self: Path) -> bytes:
        result = reader(self)
        return result[:-1] if self == path else result

    with monkeypatch.context() as scope:
        scope.setattr(Path, "read_bytes", stale_read)
        assert bp._static_file(root, "android/app/build.gradle.kts") is None

    def bad_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise PermissionError("PRIVATE_WORKSTATION")
        return stat_method(self, *args, **kwargs)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "stat", bad_stat)
        assert bp._static_file(root, "android/app/build.gradle.kts") is None


@pytest.mark.parametrize("timeout", [0, -1, 5.01, 100])
def test_git_metadata_timeout_must_be_finite(tmp_path: Path, timeout: float) -> None:
    root, _ = make_project(tmp_path)
    with pytest.raises(ValueError, match="deadline"):
        bp.AndroidBuildPreflight(root, timeout_s=timeout)


def test_git_binary_cannot_be_substituted_and_unapproved_pins_block(
    tmp_path: Path,
) -> None:
    root, checksum = make_project(tmp_path)
    with pytest.raises(ValueError, match="fixed Git"):
        bp.AndroidBuildPreflight(root, git_binary=Path("/bin/sh"))
    reader = GitRunner()
    for revision, jar_pin in (
        (None, checksum),
        (COMMIT, None),
        ("weak", checksum),
        (COMMIT, "x" * 64),
        (COMMIT, "AA" * 32),
    ):
        result = checked(
            bp.AndroidBuildPreflight(
                root,
                expected_revision=revision,
                expected_wrapper_sha256=jar_pin,
                runner=reader,
                inventory=Inventory(),  # type: ignore[arg-type]
            ).plan()
        )
        assert code(result) == ["UNAPPROVED_PIN"]
    assert reader.calls == []


def test_static_wrapper_magic_checksum_and_properties_block_bad_build(
    tmp_path: Path,
) -> None:
    root, checksum = make_project(tmp_path)
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.jar"
    properties = root / "android/gradle/wrapper/gradle-wrapper.properties"
    gradlew = root / "android/gradlew"
    gradlew.write_text("not a shell script\n")
    assert code(checked(service(root, checksum).plan())) == ["WRAPPER_UNVERIFIED"]
    gradlew.write_text("#!/bin/sh\nexit 27\n")
    assert code(checked(service(root, "0" * 64).plan())) == ["WRAPPER_SHA_MISMATCH"]
    wrapper.write_bytes(b"not even a jar")
    altered_checksum = __import__("hashlib").sha256(wrapper.read_bytes()).hexdigest()
    assert code(checked(service(root, altered_checksum).plan())) == ["WRAPPER_UNVERIFIED"]
    root, checksum = make_project(tmp_path)
    properties.write_bytes(b"\xff\xff")
    assert code(checked(service(root, checksum).plan())) == ["BUILD_METADATA_UNVERIFIED"]


@pytest.mark.parametrize(
    ("git_error", "result_code"),
    [
        (PermissionError("PRIVATE"), "PERMISSION_DENIED"),
        (OSError("PRIVATE"), "GIT_EXEC_FAILED"),
        (ValueError("PRIVATE"), "GIT_EXEC_FAILED"),
        (RuntimeError("PRIVATE"), "GIT_EXEC_FAILED"),
        (RunResult(0, "x", "", True), "OUTPUT_LIMIT"),
        (RunResult(0, "x" * 70000, "", False), "OUTPUT_LIMIT"),
        (RunResult(0, COMMIT + "\n", "PRIVATE_GIT_STDERR", False), "METADATA_UNAVAILABLE"),
    ],
)
@pytest.mark.parametrize("stage", [1, 2])
def test_git_command_failure_on_head_or_status_never_grants_plan(
    tmp_path: Path,
    git_error: BaseException | RunResult,
    result_code: str,
    stage: int,
) -> None:
    root, checksum = make_project(tmp_path)
    runner = GitRunner()
    runner.failure = git_error
    runner.fail_at = stage
    result = checked(service(root, checksum, runner=runner).plan())
    assert result["status"] == "unavailable"
    assert code(result) == [result_code]
    assert result["tasks"] == [] and result["argv_preview"] == []
    assert "PRIVATE_GIT_STDERR" not in str(result)
    assert len(runner.calls) == stage


def test_git_unknown_or_changed_revision_is_not_claimed_as_pinned(
    tmp_path: Path,
) -> None:
    root, checksum = make_project(tmp_path)
    for revision, code_name in (
        ("garbage", "REVISION_UNVERIFIED"),
        ("9" * 40, "REVISION_MISMATCH"),
        ("", "REVISION_UNVERIFIED"),
    ):
        result = checked(service(root, checksum, runner=GitRunner(revision)).plan())
        assert code(result) == [code_name]
        assert result["tasks"] == []


def test_all_fixed_actions_have_only_safe_argv_and_no_gradle_execution(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    for name, tasks in (
        ("assemble_debug", [":app:assembleDebug"]),
        ("lint_debug", [":app:lintDebug"]),
        ("test_jvm", [":native-protocol:test", ":native-lifecycle:test", ":native-mcp-jvm:test"]),
    ):
        result = checked(service(root, checksum).plan(name))
        assert result["status"] == "planned"
        assert result["tasks"] == tasks
        assert result["argv_preview"][-len(tasks) :] == tasks
        assert ("-PenableAndroidApp=true" in result["argv_preview"]) == (name != "test_jvm")
        assert result["execution_enabled"] is False


def test_no_pinned_revision_or_missing_project_never_calls_external_program(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    runner = GitRunner()
    unknown = checked(
        bp.AndroidBuildPreflight(root, expected_wrapper_sha256=checksum, runner=runner).plan()
    )
    assert code(unknown) == ["UNAPPROVED_PIN"]
    missing = checked(service(tmp_path / "absent-root", checksum, runner=runner).plan())
    assert code(missing) == ["PROJECT_ROOT_UNTRUSTED"]
    assert runner.calls == []


def test_invalid_toolchain_or_exception_returns_safe_typed_denial(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    versions = {"jdk17": "17.0.20", "sdk_platform": "36", "gradle": "9.6"}
    inventory = Inventory(versions)
    response = checked(service(root, checksum, inventory=inventory).plan())
    assert response["status"] == "unavailable"
    assert code(response) == ["TOOLCHAIN_UNAVAILABLE"]
    inventory.fail = RuntimeError("PRIVATE HOST PATH")
    response = checked(service(root, checksum, inventory=inventory).plan())
    assert response["status"] == "unavailable"
    assert code(response) == ["TOOLCHAIN_UNAVAILABLE"]
    assert "PRIVATE HOST PATH" not in str(response)


def test_git_metadata_verification_does_not_execute_gradle_or_modify_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, checksum = make_project(tmp_path)
    tracked = [p for p in root.rglob("*") if p.is_file()]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tracked}
    runner = GitRunner()
    inv = Inventory()
    planned = checked(service(root, checksum, runner=runner, inventory=inv).plan("lint_debug"))
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tracked}
    assert planned["status"] == "planned"
    assert len(runner.calls) == 2 and inv.calls == 1
    assert before == after
    assert all(
        not any(
            token in argv
            for token in (
                "build",
                "assembleDebug",
                "stash",
                "reset",
                "clean",
                "checkout",
                "update",
                "install",
            )
        )
        for argv in runner.calls
    )


def test_zip_magic_without_real_gradle_wrapper_main_is_rejected(tmp_path: Path) -> None:
    import hashlib

    root, _ = make_project(tmp_path)
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.jar"
    wrapper.write_bytes(b"PK" + b"bogus untrusted wrapper")
    checksum = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    result = checked(service(root, checksum).plan())
    assert result["status"] == "blocked"
    assert code(result) == ["WRAPPER_UNVERIFIED"]


def test_operator_project_root_dotdot_components_are_rejected(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    untrusted = root / ".."
    with pytest.raises(ValueError, match="trusted absolute"):
        bp.AndroidBuildPreflight(
            untrusted,
            expected_revision=COMMIT,
            expected_wrapper_sha256=checksum,
        )


def test_nonexecutable_gradle_wrapper_does_not_create_plan(tmp_path: Path) -> None:
    root, checksum = make_project(tmp_path)
    wrapper = root / "android/gradlew"
    wrapper.chmod(0o600)
    result = checked(service(root, checksum).plan())
    assert result["status"] == "blocked"
    assert code(result) == ["WRAPPER_UNVERIFIED"]


def test_safe_git_runner_uses_minimal_environment_for_real_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/tmp/unsafe-global-config")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/tmp/unsafe-system-config")
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/tmp/external-agent.jar")
    result = bp._safe_git_run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('GIT_CONFIG_GLOBAL')); "
            "print(os.environ.get('GIT_CONFIG_NOSYSTEM')); "
            "print(os.environ.get('GIT_OPTIONAL_LOCKS')); "
            "print(os.environ.get('JAVA_TOOL_OPTIONS'))",
        ],
        2.0,
        4096,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["/dev/null", "1", "0", "None"]


def test_true_git_head_and_dirty_status_are_read_only(
    tmp_path: Path,
) -> None:
    """Use an actual throwaway repository to ensure Git status doesn't write locks."""
    root, checksum = make_project(tmp_path)
    binary = "/usr/bin/git"
    environment = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }

    def git(*args: str) -> str:
        result = subprocess.run(
            [
                binary,
                "-C",
                str(root),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgSign=false",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                *args,
            ],
            text=True,
            capture_output=True,
            check=True,
            env=environment,
            timeout=5.0,
        )
        return result.stdout.rstrip("\n")

    git("init", "-q")
    git("add", "android")
    git("commit", "-qm", "Synthetic fixture")
    revision = git("rev-parse", "HEAD")
    assert len(revision) == 40
    index = root / ".git/index"
    previous_index = (index.read_bytes(), index.stat().st_mtime_ns)
    fixture = bp.AndroidBuildPreflight(
        root,
        expected_revision=revision,
        expected_wrapper_sha256=checksum,
        inventory=Inventory(),  # type: ignore[arg-type]
    )
    reply = checked(fixture.plan("lint_debug"))
    assert reply["status"] == "planned"
    assert reply["observed_revision"] == revision
    assert reply["dirty"] is False
    assert reply["execution_enabled"] is False
    assert (index.read_bytes(), index.stat().st_mtime_ns) == previous_index
    assert not (root / ".git/index.lock").exists()

    app = root / "android/app/build.gradle.kts"
    app.write_text(app.read_text() + "// synthetic uncommitted change\n")
    original = (app.read_bytes(), app.stat().st_mtime_ns)
    dirty = checked(fixture.plan())
    assert dirty["status"] == "blocked"
    assert dirty["dirty"] is True
    assert code(dirty) == ["DIRTY_WORKTREE"]
    assert (app.read_bytes(), app.stat().st_mtime_ns) == original
    assert (index.read_bytes(), index.stat().st_mtime_ns) == previous_index
    assert git("status", "--porcelain=v1").startswith(" M ")

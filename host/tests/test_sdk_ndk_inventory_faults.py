"""H2.a unexpected host binary, SDK metadata, symlink and error-path checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_sdk_ndk_inventory import FakeRunner, _complete_sdk, _fixture_file, _inventory

import android_mcp_host.sdk_ndk_inventory as sdk
from android_mcp_host.command_runner import OutputLimitExceeded, RunResult, bounded_run


def reason(result: dict[str, Any], name: str) -> str:
    return str(result["tools"][name]["reason"])


def test_schema_loader_requires_an_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResource:
        def joinpath(self, name: str) -> FakeResource:
            assert name == "host-sdk-ndk-inventory.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(sdk, "files", lambda _: FakeResource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        sdk.get_sdk_ndk_output_schema()


def test_fixed_candidates_and_host_abi_never_use_path_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "attack/java"))
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "attack/sdk"))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert all(path.is_absolute() for path in sdk._fixed_binary("jdk17"))
    assert all(path.is_absolute() for path in sdk._fixed_binary("gradle"))
    assert all(path.is_absolute() for path in sdk._fixed_binary("apkanalyzer_homebrew"))
    assert all(
        str(tmp_path) not in str(path)
        for name in ("jdk17", "gradle", "apkanalyzer_homebrew")
        for path in sdk._fixed_binary(name)
    )
    with pytest.raises(ValueError, match="Unsupported"):
        sdk._fixed_binary("sdkmanager")
    expected = {
        ("Darwin", "arm64"): "darwin-arm64",
        ("Darwin", "x86_64"): "darwin-x86_64",
        ("Linux", "aarch64"): "linux-aarch64",
        ("Linux", "arm64"): "linux-aarch64",
        ("Linux", "x86_64"): "linux-x86_64",
        ("Windows", "AMD64"): None,
        ("Linux", "unknown"): None,
    }
    for pair, host in expected.items():
        assert sdk._host_tag(*pair) == host
    assert sdk._version_parts("27.2.12479018") == (27, 2, 12479018)
    assert sdk._version_parts("not-a-version") is None


@pytest.mark.parametrize("timeout", [0, -1, 5.01, 100])
def test_constructor_refuses_disabled_or_excessive_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="deadline"):
        sdk.SdkNdkInventory(timeout_s=timeout)


@pytest.mark.parametrize(
    ("kwargs", "reason_part"),
    [
        ({"fixed_binaries": {"shell": Path("/bin/sh")}}, "identifier"),
        ({"sdk_root": Path("relative/sdk")}, "absolute"),
        ({"fixed_binaries": {"jdk17": Path("relative/java")}}, "absolute"),
    ],
)
def test_untrusted_configuration_is_rejected(kwargs: dict[str, Any], reason_part: str) -> None:
    with pytest.raises(ValueError, match=reason_part):
        sdk.SdkNdkInventory(**kwargs)


def test_implicit_sdk_path_is_platform_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sdk.Path, "home", lambda: Path("/some/trusted/home"))
    mac = sdk.SdkNdkInventory(system="Darwin", architecture="arm64", fixed_binaries={})
    linux = sdk.SdkNdkInventory(system="Linux", architecture="aarch64", fixed_binaries={})
    assert mac._sdk == Path("/some/trusted/home/Library/Android/sdk")
    assert linux._sdk == Path("/some/trusted/home/Android/Sdk")


def test_safe_sdk_rejects_relative_escape_and_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    assert checker._safe_sdk(root / "platforms/android-36/android.jar")
    assert checker._safe_sdk(tmp_path / "outside") is False
    protected = root / "platforms/android-36/android.jar"
    original = Path.is_symlink

    def deny(self: Path) -> bool:
        if self == protected:
            raise OSError("secret")
        return original(self)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "is_symlink", deny)
        assert checker._safe_sdk(protected) is False


def test_sdk_root_file_and_fs_faults_return_explicit_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sdk"
    root.write_text("not a directory", encoding="utf-8")
    checker = _inventory(root)
    assert checker._sdk_state()["reason"] == "SDK_ROOT_INVALID"
    root.unlink()
    root.mkdir()
    is_dir = Path.is_dir
    exists = Path.exists

    def denied_dir(self: Path) -> bool:
        if self == root:
            raise PermissionError("private sdk root")
        return is_dir(self)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "is_dir", denied_dir)
        assert checker._sdk_state()["reason"] == "PERMISSION_DENIED"

    def failed_exists(self: Path) -> bool:
        if self == root:
            raise OSError("private root error")
        return exists(self)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "exists", failed_exists)
        assert checker._sdk_state()["reason"] == "EXEC_FAILED"


def test_host_binary_missing_directory_nonexec_permission_and_stat_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _inventory(tmp_path / "unused")
    file = _fixture_file(tmp_path, "jdk17/java", executable=False)
    directory = tmp_path / "bin-directory"
    directory.mkdir()
    assert checker._binary(None)["reason"] == "NOT_INSTALLED"
    assert checker._binary(tmp_path / "missing")["reason"] == "NOT_INSTALLED"
    assert checker._binary(file)["reason"] == "NOT_EXECUTABLE"
    assert checker._binary(directory)["reason"] == "NOT_EXECUTABLE"
    file.chmod(0o700)
    with monkeypatch.context() as scope:
        scope.setattr(os, "access", lambda *args: False)
        assert checker._binary(file)["reason"] == "PERMISSION_DENIED"
    old = Path.stat
    for kind, reason_name in (
        (FileNotFoundError, "NOT_INSTALLED"),
        (PermissionError, "PERMISSION_DENIED"),
        (OSError, "EXEC_FAILED"),
    ):

        def failed_stat(self: Path, *args: Any, kind: type[OSError] = kind, **kwargs: Any) -> Any:
            if self == file:
                raise kind("sensitive filename")
            return old(self, *args, **kwargs)

        with monkeypatch.context() as scope:
            scope.setattr(Path, "stat", failed_stat)
            assert checker._binary(file)["reason"] == reason_name


def test_default_fixed_binary_selection_skips_missing_and_hostile_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    present = _fixture_file(tmp_path, "trusted/gradle")
    absent = tmp_path / "absent/gradle"
    checker = sdk.SdkNdkInventory(sdk_root=tmp_path, fixed_binaries=None)
    with monkeypatch.context() as scope:
        scope.setattr(sdk, "_fixed_binary", lambda _: (absent, present))
        assert checker._selected_binary("gradle") == present
        scope.setattr(sdk, "_fixed_binary", lambda _: (absent,))
        assert checker._selected_binary("gradle") is None
    original = Path.is_file

    def failed_file(self: Path) -> bool:
        if self == absent:
            raise OSError("private fs")
        return original(self)

    with monkeypatch.context() as scope:
        scope.setattr(sdk, "_fixed_binary", lambda _: (absent, present))
        scope.setattr(Path, "is_file", failed_file)
        assert checker._selected_binary("gradle") == present


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (subprocess.TimeoutExpired(["java"], 2), "TIMEOUT"),
        (OutputLimitExceeded("private bytes"), "OUTPUT_LIMIT"),
        (PermissionError("private key"), "PERMISSION_DENIED"),
        (OSError("private file"), "EXEC_FAILED"),
        (ValueError("private decoder"), "EXEC_FAILED"),
        (RuntimeError("private state"), "EXEC_FAILED"),
        (RunResult(2, "", "Bearer SECRET_VALUE", False), "NONZERO_EXIT"),
        (RunResult(0, "malformed", "", False), "MALFORMED_VERSION"),
        (RunResult(0, 'openjdk version "17.0.20"\n', "", True), "OUTPUT_LIMIT"),
        (RunResult(0, "x" * 70000, "", False), "OUTPUT_LIMIT"),
        (RunResult(0, "x", "s" * 70000, False), "OUTPUT_LIMIT"),
    ],
)
def test_java_runner_failure_results_are_bounded_and_redacted(
    tmp_path: Path, response: RunResult | BaseException, expected: str
) -> None:
    path = _fixture_file(tmp_path, "java")
    runner = FakeRunner({str(path): response})
    checker = _inventory(tmp_path / "absent-sdk", {"jdk17": path}, runner)
    state = checker._probe(path, ("-version",), sdk._JDK, expected="17")
    assert state["reason"] == expected
    assert state["runnable"] is False
    assert "private" not in json.dumps(state)
    assert "SECRET" not in json.dumps(state)
    assert runner.calls == [[str(path), "-version"]]


def test_platform_requires_safe_nonempty_jar_and_no_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sdk"
    checker = _inventory(root)
    assert checker._sdk_platform()["reason"] == "NOT_INSTALLED"
    jar = _fixture_file(root, "platforms/android-36/android.jar", "", executable=False)
    assert checker._sdk_platform()["reason"] == "MISSING_ARTIFACT"
    jar.write_bytes(b"not a real ZIP file")
    assert checker._sdk_platform()["reason"] == "MISSING_ARTIFACT"
    jar.unlink()
    outside = _fixture_file(tmp_path, "untrusted/external.jar", "bytes")
    jar.symlink_to(outside)
    assert checker._sdk_platform()["reason"] == "UNTRUSTED_SYMLINK"


def test_sdk_platform_stat_and_permission_failures_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sdk"
    jar = _fixture_file(root, "platforms/android-36/android.jar", "bytes")
    checker = _inventory(root)
    original = Path.is_file

    for error, expected in (
        (PermissionError, "PERMISSION_DENIED"),
        (OSError, "EXEC_FAILED"),
    ):

        def fail_path(self: Path, error: type[OSError] = error) -> bool:
            if self == jar:
                raise error("private data")
            return original(self)

        with monkeypatch.context() as scope:
            scope.setattr(Path, "is_file", fail_path)
            assert checker._sdk_platform()["reason"] == expected


def test_sdk_version_scans_skip_malformed_dirs_and_choose_latest(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    (root / "cmake/garbage").mkdir()
    (root / "cmake/4.0.0").mkdir()
    versions, issue = checker._sdk_versions("cmake")
    assert issue is None
    assert versions[0].name == "4.0.0"
    assert versions[1].name == "3.22.1"
    assert checker._cmake()["reason"] == "NOT_INSTALLED"


def test_sdk_version_symlink_and_directory_limit_rejected(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    outside = tmp_path / "bad-cmake"
    outside.mkdir()
    (root / "cmake/5.0.0").symlink_to(outside, target_is_directory=True)
    assert checker._sdk_versions("cmake")[1] == "UNTRUSTED_SYMLINK"
    (root / "cmake/5.0.0").unlink()
    for i in range(sdk.MAX_PACKAGE_ENTRIES + 1):
        (root / "cmake" / f"random-{i:03}").mkdir()
    assert checker._sdk_versions("cmake")[1] == "OUTPUT_LIMIT"


def test_sdk_version_scan_os_failures_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    original = os.scandir
    folder = root / "ndk"

    for fault, expected in (
        (PermissionError, "PERMISSION_DENIED"),
        (OSError, "EXEC_FAILED"),
    ):

        def blocked(path: Any, fault: type[OSError] = fault) -> Any:
            if Path(path) == folder:
                raise fault("private OS info")
            return original(path)

        with monkeypatch.context() as scope:
            scope.setattr(os, "scandir", blocked)
            assert checker._sdk_versions("ndk")[1] == expected


def test_ndk_missing_invalid_source_unsupported_host_and_symlink(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    assert checker._ndk()["runnable"] is True
    unsupported = _inventory(root, binaries, system="Windows", architecture="AMD64")
    assert unsupported._ndk()["reason"] == "UNSUPPORTED_HOST"
    source = root / "ndk/27.2.12479018/source.properties"
    source.unlink()
    assert checker._ndk()["reason"] == "MISSING_ARTIFACT"
    source.write_text("bad revision\n", encoding="utf-8")
    assert checker._ndk()["reason"] == "MALFORMED_VERSION"
    source.write_text("x" * (sdk.MAX_METADATA_BYTES + 5), encoding="utf-8")
    assert checker._ndk()["reason"] == "OUTPUT_LIMIT"
    source.unlink()
    outside = _fixture_file(tmp_path, "evil-source.properties", "Pkg.Revision = 28.0.1\n")
    source.symlink_to(outside)
    assert checker._ndk()["reason"] == "UNTRUSTED_SYMLINK"


def test_ndk_metadata_encoding_and_host_clang_unusable(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    source = root / "ndk/27.2.12479018/source.properties"
    source.write_bytes(b"\xff\xfe\xfd")
    assert checker._ndk()["reason"] == "EXEC_FAILED"
    source.write_text("Pkg.Revision = 27.2.12479018\n", encoding="utf-8")
    clang = root / "ndk/27.2.12479018/toolchains/llvm/prebuilt/darwin-arm64/bin/clang"
    clang.unlink()
    assert checker._ndk()["reason"] == "NOT_INSTALLED"


def test_ndk_cmake_missing_and_version_mismatch(tmp_path: Path) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    ndk = root / "ndk/27.2.12479018"
    cmake = root / "cmake/3.22.1"
    for child in sorted(ndk.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    ndk.rmdir()
    assert checker._ndk()["reason"] == "NOT_INSTALLED"
    cmake_bin = cmake / "bin/cmake"
    bad = FakeRunner({str(cmake_bin): RunResult(0, "cmake version 3.21.0\n", "", False)})
    assert _inventory(root, binaries, bad)._cmake()["reason"] == "VERSION_MISMATCH"
    cmake_bin.unlink()
    assert checker._cmake()["reason"] == "NOT_INSTALLED"


def test_sdk_root_injected_failure_is_not_an_sdk_license_grant(tmp_path: Path) -> None:
    root = tmp_path / "not-an-sdk"
    root.mkdir()
    checker = _inventory(root)
    result = checker.inspect()
    assert result["build_authorized"] is False
    assert result["sdk_licenses_verified"] is False
    assert result["status"] == "unavailable"
    assert result["build_prerequisites_present"] is False


def test_sdk_metadata_preflight_does_not_modify_any_files(tmp_path: Path) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    before = {
        str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert checker.inspect()["build_authorized"] is False
    after = {
        str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_version_probe_environment_cannot_inherit_hostile_java_or_loader_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "attacker-java"))
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/tmp/attacker.jar")
    monkeypatch.setenv("GRADLE_USER_HOME", str(tmp_path / "attacker-gradle"))
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "attacker-sdk"))
    monkeypatch.setenv("PATH", str(tmp_path / "attacker-bin"))
    # Running only the selected Python interpreter from its absolute path
    # proves SDK subprocesses receive the allowlisted process environment.
    result = sdk._safe_run(
        [
            sys.executable,
            "-c",
            "import os; print(os.getenv('JAVA_HOME')); "
            "print(os.getenv('JAVA_TOOL_OPTIONS')); "
            "print(os.getenv('GRADLE_USER_HOME')); "
            "print(os.getenv('ANDROID_HOME')); print(os.getenv('PATH'))",
        ],
        2.0,
        65536,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "None",
        "None",
        "None",
        "None",
        "/usr/bin:/bin:/opt/homebrew/bin",
    ]
    assert not result.truncated


def test_explicit_subprocess_env_isolated_from_parent_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST_SECRET_TEST_ONLY", "DO_NOT_LEAK")
    result = bounded_run(
        [
            sys.executable,
            "-c",
            "import os;print(os.getenv('HOST_SECRET_TEST_ONLY'));print(os.getenv('SAFE_VAR'))",
        ],
        2.0,
        4096,
        env={"SAFE_VAR": "passed"},
    )
    assert result.returncode == 0 and result.stdout == "None\npassed\n"
    assert os.environ["HOST_SECRET_TEST_ONLY"] == "DO_NOT_LEAK"


def test_build_tools_require_authentic_matching_sdk_metadata(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    checker = _inventory(root, binaries)
    path = root / "build-tools/36.0.0/source.properties"
    assert checker._build_tools()["runnable"] is True
    path.write_text("Pkg.Revision = 35.0.0\n", encoding="utf-8")
    assert checker._build_tools()["reason"] == "VERSION_MISMATCH"
    path.write_text("malformed revision\n", encoding="utf-8")
    assert checker._build_tools()["reason"] == "MALFORMED_VERSION"
    path.write_text("x" * (sdk.MAX_METADATA_BYTES + 10), encoding="utf-8")
    assert checker._build_tools()["reason"] == "OUTPUT_LIMIT"
    path.unlink()
    assert checker._build_tools()["reason"] == "MISSING_ARTIFACT"
    outside = _fixture_file(tmp_path, "evil-build.properties", "Pkg.Revision = 36.0.0\n")
    path.symlink_to(outside)
    assert checker._build_tools()["reason"] == "UNTRUSTED_SYMLINK"


def test_gradle_below_required_version_never_claims_build_prerequisites(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    gradle = binaries["gradle"]
    outdated = FakeRunner({str(gradle): RunResult(0, "Gradle 8.13\n", "", False)})
    report = _inventory(root, binaries, outdated).inspect()
    assert report["tools"]["gradle"]["reason"] == "VERSION_MISMATCH"
    assert report["build_prerequisites_present"] is False
    assert report["build_authorized"] is False


def test_ndk_source_revision_must_equal_verified_folder_revision(
    tmp_path: Path,
) -> None:
    root, binaries = _complete_sdk(tmp_path)
    source = root / "ndk/27.2.12479018/source.properties"
    source.write_text("Pkg.Revision = 28.1.0\n", encoding="utf-8")
    checker = _inventory(root, binaries)
    assert checker._ndk()["reason"] == "VERSION_MISMATCH"
    assert checker._ndk()["runnable"] is False

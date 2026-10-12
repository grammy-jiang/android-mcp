"""H0.b negative-path coverage and fail-closed Host provider regression tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import android_mcp_host.toolchain_inventory as inventory
from android_mcp_host.command_runner import RunResult


def _fixture_binary(tmp_path: Path, name: str = "adb") -> Path:
    candidate = tmp_path / name
    candidate.write_text("#!/bin/sh\nprintf 'Version 37.0.1\\n'\n", encoding="utf-8")
    candidate.chmod(0o700)
    return candidate


def _inventory(tmp_path: Path, **kwargs: Any) -> inventory.ToolchainInventory:
    return inventory.ToolchainInventory(
        paths=kwargs.pop("paths", {}),
        sdk_root=kwargs.pop("sdk_root", tmp_path / "not-present"),
        **kwargs,
    )


@pytest.mark.parametrize("timeout", [0.0, -1, 5.01, 60])
def test_invalid_timeout_cannot_disable_budget(tmp_path: Path, timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        _inventory(tmp_path, timeout_s=timeout)


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"paths": {"shell": Path("/usr/bin/sh")}}, "identifier"),
        ({"paths": {"adb": Path("relative/adb")}}, "absolute"),
        ({"sdk_root": Path("relative/sdk")}, "absolute"),
    ],
)
def test_untrusted_provider_configuration_is_rejected(
    tmp_path: Path, extra: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        _inventory(tmp_path, **extra)


@pytest.mark.parametrize(
    ("os_name", "suffix"), [("Darwin", "Library/Android/sdk"), ("Linux", "Android/Sdk")]
)
def test_implicit_sdk_path_is_os_specific_not_taken_from_path(
    monkeypatch: pytest.MonkeyPatch, os_name: str, suffix: str
) -> None:
    monkeypatch.setattr(inventory.platform, "system", lambda: os_name)
    result = inventory.ToolchainInventory(paths={})
    assert str(result._sdk_root).endswith(suffix)


def test_candidate_paths_reject_unknown_ids_and_ignore_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    for name in ("adb", "fastboot", "java", "gradle"):
        candidates = inventory._candidate_paths(name, tmp_path / "sdk")
        assert candidates
        assert all(p.is_absolute() for p in candidates)
        assert all(tmp_path != p.parent for p in candidates)
        assert all(p.name == name for p in candidates)
    with pytest.raises(ValueError, match="Unknown"):
        inventory._candidate_paths("sh", tmp_path)


def test_default_path_probe_skips_missing_and_selects_only_fixed_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _fixture_binary(tmp_path)
    missing = tmp_path / "absent"
    monkeypatch.setattr(inventory, "_candidate_paths", lambda name, sdk: (missing, candidate))
    calls: list[list[str]] = []

    def run(argv: Any, timeout_s: float, byte_limit: int) -> RunResult:
        calls.append(list(argv))
        return RunResult(0, "Version 37.0.1\n", "", False)

    result = _inventory(tmp_path, paths=None, runner=run)
    assert result._probe_cli("adb")["reason"] == "OK"
    assert calls == [[str(candidate), "version"]]
    monkeypatch.setattr(inventory, "_candidate_paths", lambda name, sdk: (missing,))
    assert result._probe_cli("adb")["reason"] == "NOT_INSTALLED"


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        (FileNotFoundError, "NOT_INSTALLED"),
        (PermissionError, "PERMISSION_DENIED"),
        (OSError, "EXEC_FAILED"),
    ],
)
def test_stat_failures_are_typed_without_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: type[OSError],
    expected: str,
) -> None:
    path = _fixture_binary(tmp_path)
    original_stat = Path.stat

    def stat_with_fault(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise fault("private OS error")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_fault)
    result = _inventory(tmp_path, paths={"adb": path})
    assert result._probe_cli("adb")["reason"] == expected


def test_non_regular_and_access_denied_binary_never_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "adb-directory"
    directory.mkdir()
    assert (
        _inventory(tmp_path, paths={"adb": directory})._probe_cli("adb")["reason"]
        == "NOT_EXECUTABLE"
    )
    path = _fixture_binary(tmp_path)
    monkeypatch.setattr(inventory.os, "access", lambda *args: False)
    assert (
        _inventory(tmp_path, paths={"adb": path})._probe_cli("adb")["reason"] == "PERMISSION_DENIED"
    )


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (OSError("private traceback"), "EXEC_FAILED"),
        (ValueError("bad decoder"), "PROBE_FAILED"),
        (RuntimeError("unexpected exit"), "PROBE_FAILED"),
    ],
)
def test_runner_errors_are_bounded_and_not_reflected(
    tmp_path: Path, exception: Exception, code: str
) -> None:
    path = _fixture_binary(tmp_path)

    def broken(argv: Any, timeout_s: float, byte_limit: int) -> RunResult:
        raise exception

    result = _inventory(tmp_path, paths={"adb": path}, runner=broken)._probe_cli("adb")
    assert result == {"available": True, "runnable": False, "version": None, "reason": code}
    assert str(exception) not in json.dumps(result)


@pytest.mark.parametrize(
    ("stdout", "stderr", "truncated", "expected"),
    [
        ("Version 37.0.1\n", "", False, "OK"),
        ("Version 37.0.1\n", "", True, "OUTPUT_LIMIT"),
        ("Version 37.0.1\n", "x" * 65536, False, "OUTPUT_LIMIT"),
        ("Version 37.0.1\n" + "x" * 65536, "", False, "OUTPUT_LIMIT"),
        ("Version 37.0.1 extra\n", "", False, "MALFORMED_VERSION"),
    ],
)
def test_even_malicious_or_truncated_version_output_is_bounded(
    tmp_path: Path, stdout: str, stderr: str, truncated: bool, expected: str
) -> None:
    path = _fixture_binary(tmp_path)

    def run(argv: Any, timeout_s: float, byte_limit: int) -> RunResult:
        return RunResult(0, stdout, stderr, truncated)

    assert (
        _inventory(tmp_path, paths={"adb": path}, runner=run)._probe_cli("adb")["reason"]
        == expected
    )


def test_sdk_absent_incomplete_zero_jar_and_malformed_paths(tmp_path: Path) -> None:
    sdk = tmp_path / "sdk"
    checker = _inventory(tmp_path, sdk_root=sdk)
    assert checker._probe_sdk()["reason"] == "NOT_INSTALLED"
    sdk.write_text("not-directory", encoding="utf-8")
    assert checker._probe_sdk()["reason"] == "NOT_EXECUTABLE"
    sdk.unlink()
    sdk.mkdir()
    assert checker._probe_sdk()["reason"] == "SDK_PLATFORM_NOT_FOUND"
    platform = sdk / "platforms"
    platform.mkdir()
    (platform / "android-xx").mkdir()
    (platform / "android-35").mkdir()
    (platform / "android-35" / "android.jar").touch()
    (platform / "android-36").symlink_to(platform / "android-35", target_is_directory=True)
    assert checker._probe_sdk()["reason"] == "SDK_PLATFORM_NOT_FOUND"
    (platform / "android-35" / "android.jar").write_bytes(b"synthetic")
    assert checker._probe_sdk()["version"] == "35"


@pytest.mark.parametrize(
    ("raised", "expected"), [(PermissionError, "PERMISSION_DENIED"), (OSError, "EXEC_FAILED")]
)
def test_sdk_platform_io_failure_does_not_escape_or_reflect_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: type[OSError], expected: str
) -> None:
    sdk = tmp_path / "sdk"
    (sdk / "platforms").mkdir(parents=True)
    old_scandir = os.scandir

    def error_scandir(path: Any) -> Any:
        if Path(path) == sdk / "platforms":
            raise raised("hidden sdk path or user info")
        return old_scandir(path)

    monkeypatch.setattr(inventory.os, "scandir", error_scandir)
    result = _inventory(tmp_path, sdk_root=sdk)._probe_sdk()
    assert result["reason"] == expected
    assert "hidden sdk" not in str(result)


def test_sdk_scan_has_hard_entry_limit(tmp_path: Path) -> None:
    sdk = tmp_path / "sdk"
    base = sdk / "platforms"
    base.mkdir(parents=True)
    for n in range(inventory.MAX_SDK_ENTRIES + 1):
        (base / f"unknown-{n:03d}").mkdir()
    result = _inventory(tmp_path, sdk_root=sdk)._probe_sdk()
    assert result["reason"] == "OUTPUT_LIMIT"
    assert result["runnable"] is False


def test_schema_loader_rejects_non_object_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResource:
        def joinpath(self, name: str) -> FakeResource:
            assert name.endswith(".schema.json")
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(inventory, "files", lambda _: FakeResource())
    with pytest.raises(ValueError, match="Invalid Host toolchain inventory schema"):
        inventory.get_toolchain_output_schema()


def test_cli_inventory_explicit_opt_in_and_default_legacy_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import cli

    calls: list[tuple[str, dict[str, Any]]] = []

    class StubServer:
        def run(self, **kwargs: Any) -> None:
            calls.append(("run", kwargs))

    fake_inventory = object()

    def make_server(**kwargs: Any) -> StubServer:
        calls.append(("factory", kwargs))
        return StubServer()

    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "ToolchainInventory", lambda: fake_inventory)
    monkeypatch.setattr(cli, "create_server", make_server)
    assert cli.main(["serve", "--port", "9977"]) == 0
    assert calls == [
        ("factory", {}),
        ("run", {"transport": "http", "host": "127.0.0.1", "port": 9977}),
    ]
    calls.clear()
    assert cli.main(["serve", "--port", "9977", "--toolchain-inventory"]) == 0
    assert calls == [
        ("factory", {"toolchain_inventory": fake_inventory}),
        ("run", {"transport": "http", "host": "127.0.0.1", "port": 9977}),
    ]

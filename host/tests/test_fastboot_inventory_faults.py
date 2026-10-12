"""H1.f unexpected host CLI, malicious version/transport and path denial tests."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import android_mcp_host.fastboot_inventory as fastboot
from android_mcp_host.command_runner import OutputLimitExceeded

SERIAL = "SYNTHETIC-BOOTLOADER-01"


def executable(tmp_path: Path, *, enabled: bool = True) -> Path:
    path = tmp_path / "fastboot"
    path.write_text("#!/bin/sh\nprintf 'fastboot version 37.0.1\\n'\n", encoding="utf-8")
    path.chmod(0o700 if enabled else 0o600)
    return path


def reply(
    version: subprocess.CompletedProcess[str] | BaseException,
    listing: subprocess.CompletedProcess[str] | BaseException | None = None,
    *,
    tmp_path: Path,
) -> tuple[dict[str, Any], list[list[str]]]:
    path = executable(tmp_path)
    calls: list[list[str]] = []
    values = [version, listing]

    def run(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        response = values[len(calls) - 1]
        if isinstance(response, BaseException):
            raise response
        assert response is not None
        return response

    result = fastboot.FastbootInventory(executable=path, reader=run).discover()
    return result, calls


def result_codes(value: dict[str, Any]) -> list[str]:
    return [entry["code"] for entry in value["errors"]]


@pytest.mark.parametrize("timeout", [0, -1, 10.001, 120])
def test_timeout_validation_prevents_infinite_wait(timeout: float) -> None:
    with pytest.raises(ValueError, match="deadline"):
        fastboot.FastbootInventory(timeout_s=timeout)


@pytest.mark.parametrize("parameter", ["executable", "sdk_root"])
def test_relative_fixed_binary_or_sdk_path_denied(parameter: str) -> None:
    with pytest.raises(ValueError, match="absolute"):
        fastboot.FastbootInventory(**{parameter: Path("relative/path")})


def test_default_locator_is_fixed_path_and_ignores_hostile_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = executable(tmp_path)
    hostile = tmp_path / "attacker" / "fastboot"
    hostile.parent.mkdir()
    hostile.write_text("#!/bin/sh\necho compromised\n", encoding="utf-8")
    hostile.chmod(0o700)
    monkeypatch.setenv("PATH", str(hostile.parent))
    missing = tmp_path / "missing"
    monkeypatch.setattr(fastboot, "_candidate_paths", lambda name, sdk: (missing, trusted))
    calls: list[list[str]] = []

    def reader(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, "fastboot version 37.0.1\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    inventory = fastboot.FastbootInventory(sdk_root=tmp_path, reader=reader)
    value = inventory.discover()
    assert value["status"] == "ok"
    assert calls == [[str(trusted), "--version"], [str(trusted), "devices", "-l"]]
    assert str(hostile) not in json.dumps(value)
    monkeypatch.setattr(fastboot, "_candidate_paths", lambda name, sdk: (missing,))
    value = inventory.discover()
    assert result_codes(value) == ["FASTBOOT_NOT_FOUND"]


def test_unreadable_candidate_during_discovery_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = executable(tmp_path)
    missing = tmp_path / "missing"
    original = Path.is_file

    def inspect(path: Path) -> bool:
        if path == missing:
            raise OSError("secret filesystem error")
        return original(path)

    monkeypatch.setattr(Path, "is_file", inspect)
    monkeypatch.setattr(fastboot, "_candidate_paths", lambda name, sdk: (missing, good))
    result = fastboot.FastbootInventory(sdk_root=tmp_path)._locate()
    assert result == good


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        (PermissionError, "FASTBOOT_PERMISSION_DENIED"),
        (OSError, "FASTBOOT_EXEC_FAILED"),
    ],
)
def test_stat_errors_are_failclosed_before_starting_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: type[OSError], expected: str
) -> None:
    path = executable(tmp_path)
    old = Path.stat

    def stat_with_failure(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise fault("private workstation diagnostics")
        return old(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_failure)
    response = fastboot.FastbootInventory(executable=path).discover()
    assert result_codes(response) == [expected]
    assert "private" not in str(response)


def test_nonregular_nonexecutable_and_denied_binary_are_not_launched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "not-binary"
    directory.mkdir()
    value = fastboot.FastbootInventory(executable=directory).discover()
    assert result_codes(value) == ["FASTBOOT_NOT_EXECUTABLE"]
    path = executable(tmp_path, enabled=False)
    value = fastboot.FastbootInventory(executable=path).discover()
    assert result_codes(value) == ["FASTBOOT_NOT_EXECUTABLE"]
    path.chmod(0o700)
    monkeypatch.setattr(os, "access", lambda *args, **kwargs: False)
    value = fastboot.FastbootInventory(executable=path).discover()
    assert result_codes(value) == ["FASTBOOT_PERMISSION_DENIED"]


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (subprocess.CompletedProcess([], 3, "", "SECRET_AUTH"), "FASTBOOT_VERSION_FAILED"),
        (subprocess.CompletedProcess([], 0, "garbage\n", ""), "FASTBOOT_VERSION_UNVERIFIED"),
        (
            subprocess.CompletedProcess([], 0, "fastboot version 37.0.1\n", "private stderr"),
            "FASTBOOT_VERSION_UNVERIFIED",
        ),
        (
            subprocess.CompletedProcess([], 0, "fastboot version 37.0.1\n" + "x" * 70000, ""),
            "OUTPUT_LIMIT",
        ),
    ],
)
def test_malformed_versions_and_floods_never_claim_availability(
    tmp_path: Path, version: subprocess.CompletedProcess[str], expected: str
) -> None:
    value, argv = reply(version, tmp_path=tmp_path)
    assert value["status"] == "unavailable"
    assert result_codes(value) == [expected]
    assert value["fastboot"]["available"] is False
    assert len(argv) == 1
    assert "SECRET_AUTH" not in str(value) and "private" not in str(value)


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (subprocess.TimeoutExpired(["fastboot"], 1), "FASTBOOT_TIMEOUT"),
        (OutputLimitExceeded("secret"), "OUTPUT_LIMIT"),
        (PermissionError("secret"), "FASTBOOT_PERMISSION_DENIED"),
        (OSError("secret"), "FASTBOOT_EXEC_FAILED"),
        (ValueError("secret"), "FASTBOOT_EXEC_FAILED"),
        (RuntimeError("secret"), "FASTBOOT_EXEC_FAILED"),
    ],
)
@pytest.mark.parametrize("phase", ["version", "devices"])
def test_runner_failures_at_both_stages_are_bounded_typed_and_redacted(
    tmp_path: Path, exception: BaseException, code: str, phase: str
) -> None:
    version = subprocess.CompletedProcess([], 0, "fastboot version 37.0.1\n", "")
    if phase == "version":
        response, commands = reply(exception, tmp_path=tmp_path)
    else:
        response, commands = reply(version, exception, tmp_path=tmp_path)
    assert result_codes(response) == [code]
    assert response["status"] == ("unavailable" if phase == "version" else "partial")
    assert len(commands) == (1 if phase == "version" else 2)
    assert "secret" not in str(response)


def test_list_failure_stderr_and_flood_are_distinct(tmp_path: Path) -> None:
    version = subprocess.CompletedProcess([], 0, "fastboot version 34.0.5\n", "")
    for bad, status, code in (
        (subprocess.CompletedProcess([], 2, "", "SECRET"), "partial", "FASTBOOT_LIST_FAILED"),
        (
            subprocess.CompletedProcess([], 0, "", "PRIVATE_DEVICE_INFO"),
            "partial",
            "FASTBOOT_STDERR_UNVERIFIED",
        ),
        (subprocess.CompletedProcess([], 0, "x" * 70000, ""), "partial", "OUTPUT_LIMIT"),
    ):
        result, commands = reply(version, bad, tmp_path=tmp_path)
        assert result["status"] == status and result_codes(result) == [code]
        assert "SECRET" not in str(result) and "PRIVATE" not in str(result)
        assert len(commands) == 2


def test_device_limit_duplicate_mode_and_whitespace_rows_never_authorize_devices() -> None:
    listing = "".join(f"TABLET{n} fastboot usb:1-2\n" for n in range(fastboot.MAX_DEVICES + 1))
    devices, errors = fastboot._parse_devices(listing)
    assert devices == [] and errors == ["DEVICE_LIMIT"]
    devices, errors = fastboot._parse_devices(
        "\n" + f"{SERIAL} fastboot\n" + f"{SERIAL} fastboot usb:1-2\n"
    )
    assert devices == [] and errors == ["AMBIGUOUS_FASTBOOT_SERIAL"]
    devices, errors = fastboot._parse_devices("ABC fastbootd usb:1-2\nABC unauthorized\n")
    assert devices == [] and errors == ["INVALID_FASTBOOT_MODE", "INVALID_FASTBOOT_MODE"]
    devices, errors = fastboot._parse_devices("malformed\nABC fastboot extra tokens invalid\n")
    assert devices == [] and errors == ["MALFORMED_FASTBOOT_ROW", "MALFORMED_FASTBOOT_ROW"]


def test_schema_resource_must_be_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, name: str) -> Resource:
            assert name.endswith("host-fastboot-inventory.v1.schema.json")
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(fastboot, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        fastboot.get_fastboot_output_schema()


def test_bounded_default_cli_runner_does_not_join_host_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[tuple[list[str], float, int]] = []

    def fake_bounded(
        argv: Sequence[str], timeout: float, limit: int
    ) -> subprocess.CompletedProcess[str]:
        called.append((list(argv), timeout, limit))
        return subprocess.CompletedProcess(argv, 0, "fastboot version 34.0.5\n", "")

    monkeypatch.setattr(fastboot, "completed_bounded", fake_bounded)
    fastboot._run(["/fake/fastboot", "--version"], 3.0)
    assert called == [(["/fake/fastboot", "--version"], 3.0, 65536)]

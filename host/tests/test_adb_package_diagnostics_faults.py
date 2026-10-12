"""H1.d exact package parser fuzz boundaries and domain-denial paths."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

import android_mcp_host.package_inspector as package_mod
from android_mcp_host.adb import AdbReport, Device

PKG = "com.example.app"
BASE = (
    "  Package [com.example.app] (test):\n"
    "    versionCode=123 targetSdk=36\n"
    "    versionName=1.2.3\n"
    "    requested permissions:\n"
    "      android.permission.INTERNET\n"
    "    install permissions:\n"
    "      android.permission.INTERNET: granted=true\n"
)


class FakeAdb:
    def __init__(self, executable: str | None = "/fake/adb") -> None:
        self.calls = 0
        self.executable = executable

    def inspect(self) -> AdbReport:
        self.calls += 1
        return AdbReport(
            True,
            self.executable,
            "37.0.1",
            None,
            (Device("FAKE-01", "device", {}),),
        )


def fake_runner(
    output: str = BASE,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> tuple[package_mod.PackageInspector, list[list[str]]]:
    calls: list[list[str]] = []

    def reader(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        assert timeout_s == 5.0
        return subprocess.CompletedProcess(argv, returncode, output, stderr)

    return package_mod.PackageInspector(adb=FakeAdb(), reader=reader), calls  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("a.b", True),
        ("com.example.app", True),
        ("_a._b", True),
        ("com.abc_12.abc23", True),
        ("A." + "x" * 178, True),
        ("com", False),
        ("com.2bad", False),
        ("com.example.", False),
        ("com..example", False),
        ("com.example/app", False),
        ("com.example.\n", False),
        ("com.ExámpIe", False),
        ("com.еxample", False),
        ("com.example;echo hi", False),
        ("a." + "x" * 181, False),
        (None, False),
        (["com", "example"], False),
    ],
)
def test_package_name_validation_is_strict_ascii(name: Any, valid: bool) -> None:
    assert package_mod.valid_package(name) is valid


def test_fixed_default_reader_has_shared_64k_process_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], float, int]] = []

    def fake_bounded(
        argv: Sequence[str], timeout_s: float, limit: int
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), timeout_s, limit))
        return subprocess.CompletedProcess(argv, 0, BASE, "")

    monkeypatch.setattr(package_mod, "completed_bounded", fake_bounded)
    result = package_mod._read(["/fake/adb", "-s", "FAKE-01"], 3.0)
    assert result.stdout == BASE
    assert calls == [(["/fake/adb", "-s", "FAKE-01"], 3.0, 65536)]


def test_nonobject_packaged_schema_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resource:
        def joinpath(self, _: str) -> Resource:
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(package_mod, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        package_mod.get_package_output_schema()


@pytest.mark.parametrize("seconds", [-3.0, 0.0, 10.1, 120.0])
def test_timeout_is_bounded(seconds: float) -> None:
    with pytest.raises(ValueError, match="deadline"):
        package_mod.PackageInspector(timeout_s=seconds)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("versionCode=0 targetSdk=1", 0),
        ("versionCode=999999999999 targetSdk=100", 999999999999),
        ("versionCode=1000000000000 targetSdk=35", None),
        ("versionCode=INVALID targetSdk=35", None),
        ("versionCode=1\nversionCode=2", None),
        ("versionCode=9999999999999", None),
        ("", None),
    ],
)
def test_numeric_parser_bounds_and_ambiguity(text: str, expected: int | None) -> None:
    assert package_mod._single_number(package_mod._VERSION_CODE, text, 0, 999999999999) == expected


def test_section_extraction_never_matches_similarly_named_package() -> None:
    assert (
        package_mod._selected_section(
            "  Package [com.example.app2] (x):\n    versionName=SECRET\n",
            PKG,
        )
        is None
    )
    assert (
        package_mod._selected_section(
            BASE + "\n  Package [com.example.app] (duplicate):\n",
            PKG,
        )
        is None
    )
    selected = package_mod._selected_section(
        "  Package [com.example.app] (first):\n    versionName=1.0\n"
        "  Package [com.example.app2] (private):\n    versionName=SECRET\n",
        PKG,
    )
    assert selected is not None
    assert "SECRET" not in selected
    assert "1.0" in selected
    assert (
        package_mod._selected_section("  Package [com.example.app]:\n    versionName=1.0\n", PKG)
        is not None
    )


def test_duplicate_permissions_must_be_deduplicated_for_wire_schema() -> None:
    repeated = BASE.replace(
        "      android.permission.INTERNET\n",
        "      android.permission.INTERNET\n      android.permission.INTERNET\n",
    ).replace(
        "      android.permission.INTERNET: granted=true\n",
        "      android.permission.INTERNET: granted=true\n"
        "      android.permission.INTERNET: granted=true\n",
    )
    parsed = package_mod._parse(repeated, PKG, True, 32)
    assert parsed is not None
    assert parsed["requested_permissions"] == ["android.permission.INTERNET"]
    assert parsed["granted_permissions"] == ["android.permission.INTERNET"]


def test_permission_sections_omit_malformed_rows_and_obey_limit() -> None:
    section = (
        " requested permissions:\n"
        "  android.permission.CAMERA\n"
        "  shell;rm /tmp/secrets\n"
        "  android.permission.POST_NOTIFICATIONS\n"
        " install permissions:\n"
        "  android.permission.CAMERA: granted=true\n"
        "  android.permission.POST_NOTIFICATIONS: granted=false\n"
        "  android.permission.BLUETOOTH_CONNECT: granted=true\n"
    )
    requested, granted, clipped = package_mod._permissions(section, 1)
    assert requested == ["android.permission.CAMERA"]
    assert granted == ["android.permission.CAMERA"]
    assert clipped is True
    assert "shell" not in str((requested, granted))


def test_permission_metadata_optout_is_explicit_no_permission_output() -> None:
    service, calls = fake_runner()
    result = service.inspect("FAKE-01", PKG, include_permissions=False)
    assert result["status"] == "ok"
    assert result["found"] is True
    assert result["requested_permissions"] == []
    assert result["granted_permissions"] == []
    assert not result["permissions_truncated"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("version_lines", "expected"),
    [
        ("versionCode=123 targetSdk=35\nversionName=1.0\n", "ok"),
        ("versionCode=123 targetSdk=35\n", "partial"),
        ("versionCode=123 targetSdk=999\nversionName=1.0\n", "partial"),
        ("versionCode=abc targetSdk=35\nversionName=1.0\n", "partial"),
        ("versionCode=123 targetSdk=35\nversionName=1.0\nversionName=2.0\n", "partial"),
    ],
)
def test_partial_package_metadata_never_fabricates_version(
    version_lines: str, expected: str
) -> None:
    output = "  Package [com.example.app] (test):\n" + version_lines
    service, calls = fake_runner(output)
    result = service.inspect("FAKE-01", PKG)
    assert result["status"] == expected
    assert result["found"] is True
    assert len(calls) == 1
    if expected == "partial":
        assert result["errors"][0]["code"] == "PARTIAL_DATA"


def test_malformed_utf8_is_never_echoed_or_treated_as_valid_metadata() -> None:
    service, _ = fake_runner(BASE + "\ufffd")
    response = service.inspect("FAKE-01", PKG)
    assert response["status"] == "unavailable"
    assert response["errors"][0]["code"] == "PACKAGE_VISIBILITY_UNKNOWN"
    assert "\ufffd" not in json.dumps(response)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OSError("secret/abs/path"), "PROBE_EXEC_FAILED"),
        (RuntimeError("secret/token"), "PROBE_EXEC_FAILED"),
        (ValueError("secret"), "PROBE_EXEC_FAILED"),
    ],
)
def test_reader_errors_are_typed_and_redacted(failure: BaseException, expected: str) -> None:
    def broken(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        raise failure

    result = package_mod.PackageInspector(adb=FakeAdb(), reader=broken).inspect(  # type: ignore[arg-type]
        "FAKE-01", PKG
    )
    assert result["status"] == "error"
    assert [e["code"] for e in result["errors"]] == [expected]
    assert "secret" not in json.dumps(result)


def test_fake_reader_permission_failure_has_distinct_reason_and_no_secret() -> None:
    def forbidden(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        raise PermissionError("SECRET_ACCESS_DENIED")

    result = package_mod.PackageInspector(adb=FakeAdb(), reader=forbidden).inspect(  # type: ignore[arg-type]
        "FAKE-01", PKG
    )
    assert result["status"] == "error" and result["errors"][0]["code"] == "PERMISSION_DENIED"
    assert "SECRET" not in str(result)


def test_no_adb_binary_never_chooses_global_or_unscoped_adb() -> None:
    adb = FakeAdb(executable=None)
    result = package_mod.PackageInspector(adb=adb).inspect(  # type: ignore[arg-type]
        "FAKE-01", PKG
    )
    assert result["status"] == "error" and result["errors"][0]["code"] == "ADB_NOT_FOUND"
    assert adb.calls == 1


def test_nonzero_exit_indicates_exact_package_not_found_only_with_marker() -> None:
    for output, stderr, code in (
        ("", "Unable to find package com.example.app", "PACKAGE_NOT_FOUND"),
        ("Package not found", "", "PACKAGE_NOT_FOUND"),
        ("Unknown package", "", "PACKAGE_NOT_FOUND"),
        ("", "com.example.other; TOKEN=SECRET", "PROBE_FAILED"),
    ):
        service, calls = fake_runner(output, stderr=stderr, returncode=42)
        result = service.inspect("FAKE-01", PKG)
        assert result["status"] == "error"
        assert result["errors"][0]["code"] == code
        assert len(calls) == 1
        assert "SECRET" not in str(result)


def test_successful_nonempty_untrusted_stderr_returns_typed_partial() -> None:
    service, _ = fake_runner(stderr="Bearer SECRET_VALUE")
    result = service.inspect("FAKE-01", PKG)
    assert result["status"] == "partial"
    assert result["errors"][0]["code"] == "PARTIAL_DATA"
    assert "SECRET_VALUE" not in str(result)


def test_known_missing_package_string_is_unavailable_not_a_success() -> None:
    service, _ = fake_runner("Unable to find package com.example.app")
    result = service.inspect("FAKE-01", PKG)
    assert result["status"] == "unavailable"
    assert result["errors"][0]["code"] == "PACKAGE_NOT_FOUND"


def test_no_version_permission_output_legacy_tool_remains_separate() -> None:
    parsed = package_mod._parse(BASE, PKG, False, 4)
    assert parsed is not None
    assert parsed["requested_permissions"] == []
    assert parsed["granted_permissions"] == []


def test_public_schema_requires_unique_permissions() -> None:
    from jsonschema import Draft202012Validator

    service, _ = fake_runner()
    valid = service.inspect("FAKE-01", PKG)
    Draft202012Validator(package_mod.get_package_output_schema()).validate(valid)
    duplicate = dict(valid, requested_permissions=["android.permission.CAMERA"] * 2)
    assert not Draft202012Validator(package_mod.get_package_output_schema()).is_valid(duplicate)

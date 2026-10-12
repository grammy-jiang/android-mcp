"""H1.e negative-path and resource-budget tests using only synthetic data."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

import android_mcp_host.logcat_filters as logs
from android_mcp_host.adb import AdbReport, Device


class FakeAdb:
    def __init__(self, binary: str | None = "/fake/adb") -> None:
        self.binary = binary
        self.calls = 0

    def inspect(self) -> AdbReport:
        self.calls += 1
        return AdbReport(True, self.binary, "37", None, (Device("FIXTURE-01", "device", {}),))


def line(message: str = "safe", tag: str = "Demo", priority: str = "I") -> str:
    return f"10-12 12:34:56.789  100  120 {priority} {tag}: {message}\n"


def codes(result: dict[str, Any]) -> list[str]:
    return [error["code"] for error in result["errors"]]


def test_packaged_schema_invalid_top_level_object_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Resource:
        def joinpath(self, file: str) -> Resource:
            assert file.endswith("host-logcat-filters.v1.schema.json")
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(logs, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        logs.get_logcat_output_schema()


def test_default_reader_uses_strict_byte_capture_and_arg_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], float, int]] = []

    def fake_runner(
        argv: Sequence[str], timeout: float, byte_limit: int
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), timeout, byte_limit))
        return subprocess.CompletedProcess(argv, 0, line(), "")

    monkeypatch.setattr(logs, "completed_bounded", fake_runner)
    response = logs._read(["/fixture/adb", "-s", "FIXTURE-01", "logcat"], 2.5)
    assert "Demo" in response.stdout
    assert calls == [(["/fixture/adb", "-s", "FIXTURE-01", "logcat"], 2.5, 65536)]


@pytest.mark.parametrize(
    ("tag", "severity", "count"),
    [
        (None, None, 3),
        ("Demo", None, 2),
        (None, "W", 1),
        ("Demo", "E", 1),
        ("Demo", "F", 0),
    ],
)
def test_python_filters_enforce_tag_priority_independently_of_adb_cli(
    tag: str | None, severity: str | None, count: int
) -> None:
    sample = line("one", priority="I") + line("two", priority="E") + line("three", tag="Other")
    records, incomplete = logs._records(sample, device_id="FIXTURE-01", tag=tag, severity=severity)
    assert len(records) == count
    assert incomplete is False


def test_logcat_record_parser_reports_invalid_utf8_tag_and_rows_without_raw_data() -> None:
    output = (
        "\n"
        + line("okay")
        + line("bad \ufffd replacement")
        + line("hidden", tag="Bad Tag")
        + "unparseable SECRET_TOKEN\n"
    )
    parsed, partial = logs._records(output, device_id="FIXTURE-01", tag=None, severity=None)
    assert partial is True
    assert parsed == [{"priority": "I", "tag": "Demo", "message": "okay"}]
    assert "SECRET_TOKEN" not in json.dumps(parsed)


def test_capture_cap_limits_both_line_count_and_total_text() -> None:
    many = line("x") * (logs.MAX_LINES + 8)
    parsed, partial = logs._records(many, device_id="FIXTURE-01", tag=None, severity=None)
    assert len(parsed) == logs.MAX_LINES and partial is True
    longline = line("x" * (logs.MAX_MESSAGE + 80))
    parsed, partial = logs._records(longline, device_id="FIXTURE-01", tag=None, severity=None)
    assert partial is True and len(parsed[0]["message"]) == logs.MAX_MESSAGE
    big = line("x" * logs.MAX_MESSAGE) * 45
    parsed, partial = logs._records(big, device_id="FIXTURE-01", tag=None, severity=None)
    assert partial is True
    assert sum(len(item["message"]) for item in parsed) == logs.MAX_TOTAL_MESSAGE
    assert all(len(item["message"]) <= logs.MAX_MESSAGE for item in parsed)


def test_sanitize_strips_control_escapes_and_nonstrings_are_not_injected() -> None:
    result = logs._sanitize(
        "\x1b[31mHello\x1b[0m\x00\tabc\r" + "FIXTURE-01" + " \u2603",
        "FIXTURE-01",
    )
    assert "Hello" in result
    assert "FIXTURE-01" not in result
    assert "[DEVICE]" in result
    assert "\x1b" not in result and "\x00" not in result and "\u2603" not in result
    assert logs._sanitize("A!" * 350, "") == "A!" * 256


def test_unavailable_binary_produces_typed_denial_and_no_fallback() -> None:
    calls: list[list[str]] = []

    def forbidden(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        raise AssertionError("Should never start a subprocess")

    result = logs.LogcatFilters(adb=FakeAdb(None), reader=forbidden).capture("FIXTURE-01")  # type: ignore[arg-type]
    assert result["status"] == "error"
    assert codes(result) == ["ADB_NOT_FOUND"]
    assert calls == []


@pytest.mark.parametrize(
    ("pid_output", "pid_code", "pid_stderr", "error"),
    [
        ("", 0, "", "PROCESS_NOT_RUNNING"),
        ("", 1, "", "PROCESS_NOT_RUNNING"),
        ("100 200\n", 0, "", "AMBIGUOUS_PROCESS"),
        ("not-a-pid\n", 0, "", "AMBIGUOUS_PROCESS"),
        ("0\n", 0, "", "AMBIGUOUS_PROCESS"),
        ("9" * 9, 0, "", "AMBIGUOUS_PROCESS"),
        ("1234\n", 0, "private", "PROCESS_UNKNOWN"),
    ],
)
def test_exact_package_resolution_never_guesses_wrong_or_multiple_pid(
    pid_output: str, pid_code: int, pid_stderr: str, error: str
) -> None:
    calls: list[list[str]] = []

    def fake(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, pid_code, pid_output, pid_stderr)

    capture = logs.LogcatFilters(adb=FakeAdb(), reader=fake)  # type: ignore[arg-type]
    result = capture.capture("FIXTURE-01", package="com.example.app")
    assert codes(result) == [error]
    assert result["status"] == "error"
    assert len(calls) == 1
    assert calls[0] == ["/fake/adb", "-s", "FIXTURE-01", "shell", "pidof", "com.example.app"]
    assert "private" not in str(result)


@pytest.mark.parametrize(
    ("fault", "status", "error"),
    [
        (PermissionError("SECRET"), "partial", "PERMISSION_DENIED"),
        (OSError("SECRET"), "partial", "LOGCAT_EXEC_FAILED"),
        (RuntimeError("SECRET"), "partial", "LOGCAT_EXEC_FAILED"),
        (ValueError("SECRET"), "partial", "LOGCAT_EXEC_FAILED"),
    ],
)
def test_reader_failure_classified_and_never_reflects_sensitive_exception(
    fault: Exception, status: str, error: str
) -> None:
    def broken(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise fault

    result = logs.LogcatFilters(adb=FakeAdb(), reader=broken).capture("FIXTURE-01")  # type: ignore[arg-type]
    assert result["status"] == status and codes(result) == [error]
    assert "SECRET" not in str(result)


def test_pid_resolution_timeout_is_typed_and_returns_no_partial_raw_data() -> None:
    def blocked(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, timeout)

    result = logs.LogcatFilters(adb=FakeAdb(), reader=blocked).capture(  # type: ignore[arg-type]
        "FIXTURE-01", package="com.example.app"
    )
    assert result["status"] == "timeout"
    assert codes(result) == ["LOGCAT_TIMEOUT"] and result["entries"] == []


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "expected"),
    [
        (line(), "", 10, "LOGCAT_FAILED"),
        (line(), "private stderr", 0, "PARTIAL_DATA"),
        ("x" * 70000, "", 0, "OUTPUT_LIMIT"),
        (line(), "SECRET" * 15000, 0, "OUTPUT_LIMIT"),
    ],
)
def test_reader_nonzero_stderr_and_overlimit_results_fail_closed(
    stdout: str, stderr: str, returncode: int, expected: str
) -> None:
    def fake(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    result = logs.LogcatFilters(adb=FakeAdb(), reader=fake).capture("FIXTURE-01")  # type: ignore[arg-type]
    assert codes(result) == [expected]
    assert result["status"] != "ok"
    assert "private stderr" not in str(result)


def test_severity_only_uses_fixed_filterspec_not_unbounded_shell() -> None:
    calls: list[list[str]] = []

    def reader(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, line("event", priority="E"), "")

    result = logs.LogcatFilters(adb=FakeAdb(), reader=reader).capture(  # type: ignore[arg-type]
        "FIXTURE-01", severity="E", lines=30
    )
    assert result["status"] == "ok"
    assert calls == [
        ["/fake/adb", "-s", "FIXTURE-01", "logcat", "-d", "-t", "30", "-v", "threadtime", "*:E"]
    ]

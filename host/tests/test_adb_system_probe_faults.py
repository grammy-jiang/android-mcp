"""H1.c field parsers, fixed argv, resource and domain-failure regressions."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

import android_mcp_host.system_snapshot as system
from android_mcp_host.adb import AdbReport, Device


class FixedAdb:
    def __init__(self, *, executable: str | None = "/fake/adb") -> None:
        self.calls = 0
        self.executable = executable

    def inspect(self) -> AdbReport:
        self.calls += 1
        return AdbReport(
            True,
            self.executable,
            "37",
            None,
            (Device("FAKE-01", "device", {"transport_id": "7"}),),
        )


def _service(
    stdout: str = "Physical size: 2560x1600\n",
    *,
    executable: str | None = "/fake/adb",
    returncode: int = 0,
    stderr: str = "",
) -> tuple[system.SystemSnapshot, list[list[str]]]:
    calls: list[list[str]] = []

    def reader(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return system.SystemSnapshot(adb=FixedAdb(executable=executable), reader=reader), calls  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1),
        ("100", 100),
        ("101", None),
        ("0", None),
        ("-1", None),
        ("1.4", None),
        ("１２", None),
        ("1" * 32, None),
        ("x", None),
        ("", None),
    ],
)
def test_bounded_numeric_parser_rejects_untrusted_text(raw: str, expected: int | None) -> None:
    assert system._number(raw, 1, 100) == expected


def test_field_extraction_handles_missing_and_duplicate_dumpsys_entries() -> None:
    assert system._dumpsys_field("level: 4\n", "level") == "4"
    assert system._dumpsys_field("level: 4\nlevel: 9\n", "level") is None
    assert system._dumpsys_field("token: secret\n", "level") is None
    assert system._dumpsys_field("AC powered: false\n", "AC powered") == "false"


@pytest.mark.parametrize(
    ("key", "text", "value"),
    [
        ("api_level", "36\n", {"api_level": 36}),
        ("api_level", "hello\n", {}),
        ("model", "Pixel 10\n", {"model": "Pixel 10"}),
        ("model", "Bad\nPassword: SECRET\n", {}),
        ("model", "Bad\u001bModel\n", {}),
        ("model", "x" * 120, {}),
        (
            "battery",
            "level: 0\nscale: 100\nAC powered: false\n",
            {"battery_percent": 0.0, "battery_ac_powered": False},
        ),
        ("battery", "level: 50\nscale: 0\ntemperature: 250\n", {"battery_temperature_c": 25.0}),
        ("battery", "level: 50\nscale: 100\nlevel: 30\n", {}),
        (
            "battery",
            "level: 70\nscale: 100\nAC powered: false\n",
            {"battery_percent": 70.0, "battery_ac_powered": False},
        ),
        ("battery", "temperature: 9999\nAC powered: yes\n", {}),
        ("storage", "header only\n", {}),
        ("storage", "header\na b 123 1 23% /data\n", {}),
        (
            "storage",
            "header\n/dev/a 1000 200 700 25% /data\n",
            {"total_kib": 1000, "free_kib": 700},
        ),
        ("storage", "header\n/dev/a 100 200 200 25% /data\n", {}),
        ("storage", "header\n/dev/a 100 20 80 20% /data\n/dev/a 100 20 80 20% /data\n", {}),
        ("size", "Override size: 2560x1600\n", {}),
        ("size", "Physical size: 2560x1600\n", {"width_px": 2560, "height_px": 1600}),
        ("size", "Physical size: 15x1600\n", {}),
        ("size", "Physical size: 99999x1600\n", {}),
        ("density", "Physical density: 320\n", {"density_dpi": 320}),
        ("density", "Override density: 320\n", {}),
        ("density", "Physical density: 9999\n", {}),
        ("network", "Active default network: null\n", {"default_network_connected": False}),
        ("network", "Active default network: 123\n", {"default_network_connected": True}),
        ("network", "Active default network: app_secret_192.0.2.1\n", {}),
        ("unknown", "true\n", {}),
    ],
)
def test_parsers_return_only_valid_typed_fields_without_raw_text(
    key: str, text: str, value: dict[str, Any]
) -> None:
    assert system._parse(key, text) == value


@pytest.mark.parametrize("payload", [b"\xff".decode("utf-8", errors="replace"), "x" * 70000, 12])
def test_invalid_utf8_and_oversized_outputs_never_become_typed_values(payload: Any) -> None:
    assert system._parse("model", payload) == {}


@pytest.mark.parametrize("deadline", [-1, 0, 10.01, 100])
def test_timeouts_must_remain_finite_and_tight(deadline: float) -> None:
    with pytest.raises(ValueError, match="deadline"):
        system.SystemSnapshot(timeout_s=deadline)


def test_missing_discovery_binary_does_not_fallback_to_path() -> None:
    service, calls = _service(executable=None)
    result = service.inspect("FAKE-01", ["display"])
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "ADB_NOT_FOUND"
    assert calls == []


@pytest.mark.parametrize(
    "failure", [OSError("hidden"), RuntimeError("hidden"), ValueError("hidden")]
)
def test_reader_unexpected_failures_are_typed_and_redacted(failure: Exception) -> None:
    def broken(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        raise failure

    service = system.SystemSnapshot(adb=FixedAdb(), reader=broken)  # type: ignore[arg-type]
    result = service.inspect("FAKE-01", ["battery"])
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "PROBE_EXEC_FAILED"
    assert "hidden" not in json.dumps(result)


def test_nonzero_status_does_not_reflect_sensitive_stderr() -> None:
    service, calls = _service(returncode=9, stderr="Bearer PRIVATE_KEY")
    result = service.inspect("FAKE-01", ["display"])
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "PROBE_FAILED"
    assert "PRIVATE_KEY" not in json.dumps(result)
    assert calls == [["/fake/adb", "-s", "FAKE-01", "shell", "wm", "size"]]


def test_fake_output_flood_is_caught_even_if_reader_ignores_budget() -> None:
    service, _ = _service(stdout="x" * 70000)
    reply = service.inspect("FAKE-01", ["display"])
    assert reply["status"] == "error" and reply["errors"][0]["code"] == "OUTPUT_LIMIT"
    assert "x" * 100 not in json.dumps(reply)


def test_successful_output_with_stderr_is_partial_and_secret_free() -> None:
    service, _ = _service(stderr="PASSWORD=hidden")
    reply = service.inspect("FAKE-01", ["display"])
    assert reply["status"] == "partial"
    assert [e["code"] for e in reply["errors"]] == ["PARTIAL_DATA"]
    assert "hidden" not in json.dumps(reply)
    assert reply["results"][0]["values"]["width_px"] == 2560


def test_unsupported_or_ambiguous_result_fields_do_not_claim_success() -> None:
    service, _ = _service(stdout="Unparseable data without Physical size")
    reply = service.inspect("FAKE-01", ["display"])
    assert reply["status"] == "partial"
    assert reply["results"][0]["values"] == {}
    assert [e["code"] for e in reply["errors"]] == ["PARTIAL_DATA"]


def test_package_schema_loader_requires_object_not_json_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Resource:
        def joinpath(self, filename: str) -> Resource:
            assert filename.endswith("host-system-snapshot.v1.schema.json")
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(system, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        system.get_snapshot_output_schema()


def test_default_bounded_runner_uses_explicit_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], float, int]] = []

    def fake_bounded(
        argv: Sequence[str], timeout_s: float, limit: int
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), timeout_s, limit))
        return subprocess.CompletedProcess(argv, 0, "fixed\n", "")

    monkeypatch.setattr(system, "completed_bounded", fake_bounded)
    reply = system._run(["/fake/adb", "-s", "FAKE-01", "shell", "getenforce"], 3.0)
    assert reply.stdout == "fixed\n"
    assert calls == [(["/fake/adb", "-s", "FAKE-01", "shell", "getenforce"], 3.0, 65536)]

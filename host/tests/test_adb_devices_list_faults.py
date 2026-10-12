"""H1.a safety contract adversarial cases for device listing and opt-in CLI."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

import android_mcp_host.device_discovery as discovery
from android_mcp_host.adb import AdbReport, Device, Diagnostic


class FakeAdb:
    def __init__(self, report: AdbReport) -> None:
        self.report = report
        self.calls = 0

    def inspect(self) -> AdbReport:
        self.calls += 1
        return self.report


def _report(*devices: Device, available: bool = True, error: Diagnostic | None = None) -> AdbReport:
    return AdbReport(available, "/synthetic/adb", "37", error, devices)


def _run(report: AdbReport) -> dict[str, Any]:
    fake = FakeAdb(report)
    result = discovery.DeviceDiscovery(fake).list_devices()  # type: ignore[arg-type]
    assert fake.calls == 1
    Draft202012Validator(discovery.get_device_list_output_schema()).validate(result)
    return result


def _codes(result: dict[str, Any]) -> list[str]:
    return [item["code"] for item in result["errors"]]


def test_advertised_schema_is_canonical_and_invalid_extra_fields_rejected() -> None:
    schema = discovery.get_device_list_output_schema()
    assert schema["$id"] == "urn:android-mcp:adb-device-list:v1"
    Draft202012Validator.check_schema(schema)
    baseline = _run(_report())
    altered = {**baseline, "unexpected_permission": "granted"}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(altered)


def test_package_schema_loader_rejects_nonobject(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubResource:
        def joinpath(self, name: str) -> StubResource:
            assert name == "host-adb-device-list.v1.schema.json"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(discovery, "files", lambda _: StubResource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        discovery.get_device_list_output_schema()


@pytest.mark.parametrize(
    ("report", "expected_status", "code"),
    [
        (_report(available=False), "unavailable", "ADB_NOT_FOUND"),
        (
            _report(error=Diagnostic("PRIVATE_UNEXPECTED_ERROR", "API_TOKEN=private")),
            "partial",
            "ADB_DISCOVERY_FAILED",
        ),
        (
            _report(error=Diagnostic("ADB_TIMEOUT", "secret"), available=False),
            "unavailable",
            "ADB_TIMEOUT",
        ),
    ],
)
def test_availability_and_unknown_daemon_error_are_fail_closed(
    report: AdbReport, expected_status: str, code: str
) -> None:
    result = _run(report)
    assert result["devices"] == []
    assert result["status"] == expected_status
    assert _codes(result) == [code]
    assert "API_TOKEN" not in str(result)
    assert "secret" not in str(result)


def test_more_than_64_devices_are_rejected_without_unbounded_echo() -> None:
    targets = tuple(
        Device(f"SYNTHETIC-{number}", "device", {"transport_id": str(number + 1)})
        for number in range(65)
    )
    result = _run(_report(*targets))
    assert result["status"] == "error"
    assert result["devices"] == []
    assert _codes(result) == ["DEVICE_LIMIT"]


def test_malformed_rows_cannot_become_ready_or_get_reflected() -> None:
    result = _run(
        _report(
            Device("-s", "device", {"transport_id": "1"}),
            Device("SYNTHETIC-INVALID", "bogus", {"transport_id": "2"}),
        )
    )
    assert result["status"] == "partial"
    assert result["devices"] == []
    assert _codes(result) == ["MALFORMED_DEVICE_ROW", "MALFORMED_DEVICE_ROW"]
    assert "bogus" not in str(result)


@pytest.mark.parametrize("state", ["offline", "unauthorized", "recovery", "authorizing"])
def test_missing_transport_nonready_state_remains_honestly_not_ready(state: str) -> None:
    result = _run(_report(Device("SYNTHETIC-ONE", state, {})))
    assert result["status"] == "ok"
    assert result["devices"][0]["ready_for_read"] is False
    assert result["devices"][0]["transport_id"] is None
    assert result["errors"] == []


@pytest.mark.parametrize("transport", ["0", "0001", "1;reboot", "abc", "", "12345678901"])
def test_invalid_transport_id_is_partial_and_not_actionable(transport: str) -> None:
    result = _run(_report(Device("SYNTHETIC-ONE", "device", {"transport_id": transport})))
    assert result["status"] == "partial"
    assert result["devices"][0]["transport_id"] is None
    assert result["devices"][0]["ready_for_read"] is False
    assert _codes(result) == ["MISSING_TRANSPORT_ID"]


def test_no_implicit_device_selection_from_first_of_multiple() -> None:
    result = _run(
        _report(
            Device("SYNTHETIC-FIRST", "unauthorized", {"transport_id": "7"}),
            Device("SYNTHETIC-SECOND", "device", {"transport_id": "8"}),
        )
    )
    assert result["status"] == "ok"
    assert [device["device_id"] for device in result["devices"]] == [
        "SYNTHETIC-FIRST",
        "SYNTHETIC-SECOND",
    ]
    assert [device["ready_for_read"] for device in result["devices"]] == [False, True]
    assert "selected_device" not in result


def test_device_discovery_uses_default_adapter_without_implicit_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoDeviceAdb:
        def inspect(self) -> AdbReport:
            return _report()

    monkeypatch.setattr(discovery, "AdbClient", NoDeviceAdb)
    result = discovery.DeviceDiscovery().list_devices()
    assert result["status"] == "ok" and result["devices"] == []


def test_cli_opt_in_registers_only_bounded_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    from android_mcp_host import cli

    calls: list[tuple[str, Any]] = []
    provider = object()

    class FakeServer:
        def run(self, **kwargs: Any) -> None:
            calls.append(("run", kwargs))

    def create(**kwargs: Any) -> FakeServer:
        calls.append(("create", kwargs))
        return FakeServer()

    monkeypatch.setattr(cli, "DeviceDiscovery", lambda: provider)
    monkeypatch.setattr(cli, "create_server", create)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    assert cli.main(["serve", "--adb-devices-list", "--port", "9661"]) == 0
    assert calls == [
        ("create", {"adb_discovery": provider}),
        ("run", {"transport": "http", "host": "127.0.0.1", "port": 9661}),
    ]


def test_cli_rejects_remote_bind_even_with_discovery_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import cli

    def never_construct(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not configure Tool after invalid remote bind")

    monkeypatch.setattr(cli, "create_server", never_construct)
    with pytest.raises(SystemExit) as error:
        cli.main(["serve", "--host", "0.0.0.0", "--adb-devices-list"])
    assert error.value.code == 2

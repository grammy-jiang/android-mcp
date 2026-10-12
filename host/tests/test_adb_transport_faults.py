"""H1.b adversarial, deadline and parser-specific transport diagnostics tests."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from collections.abc import Sequence
from typing import Any

import pytest
from fastmcp import Client

from android_mcp_host.adb import AdbReport, Device, Diagnostic
from android_mcp_host.adb_transport import (
    MAX_MDNS_SERVICES,
    MAX_ROUTES,
    AdbTransport,
    _endpoint_valid,
    _mdns,
    _routes,
    get_transport_output_schema,
)
from android_mcp_host.command_runner import OutputLimitExceeded


def report(
    *,
    serial: str = "FIXTURE-01",
    state: str = "device",
    transport: str = "7",
    executable: str | None = "/fake/adb",
    available: bool = True,
    error: Diagnostic | None = None,
    other: tuple[Device, ...] = (),
) -> AdbReport:
    return AdbReport(
        available,
        executable,
        "37",
        error,
        (Device(serial, state, {"transport_id": transport}), *other),
    )


class Fake:
    def __init__(self, *reports: AdbReport) -> None:
        self.reports = reports
        self.calls = 0

    def inspect(self) -> AdbReport:
        current = self.reports[min(self.calls, len(self.reports) - 1)]
        self.calls += 1
        return current


class Runner:
    def __init__(
        self, replies: list[subprocess.CompletedProcess[str] | BaseException] | None = None
    ) -> None:
        self.replies = replies if replies is not None else []
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: Sequence[str], timeout_s: float, byte_limit: int
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        assert 0 < timeout_s <= 3 and byte_limit == 65536
        if not self.replies:
            return subprocess.CompletedProcess(argv, 0, "", "")
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def run(
    *reports: AdbReport,
    reader: Runner | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    service = AdbTransport(adb=Fake(*reports), runner=reader or Runner())  # type: ignore[arg-type]
    return service.inspect(device_id="FIXTURE-01", transport_id="7", **kwargs)


def codes(value: dict[str, Any]) -> list[str]:
    return [e["code"] for e in value["errors"]]


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("10.1.2.3:12345", True),
        ("fixture.local:4321", True),
        ("[::1]:3333", True),
        ("[2001:db8::1]:36555", True),
        ("10.1.2.3:0", False),
        ("127.0.0.1:99999", False),
        ("127.0.0.999:4001", False),
        ("foo..local:4001", False),
        ("host.:4001", False),
        ("-evil.local:4001", False),
        ("evil-.local:4001", False),
        ("foo:4001", False),
        ("[wrong]:4001", False),
        ("[fe80::1%eth0]:4444", False),
        ("evil.local:4000; rm -rf /", False),
        ("evil.local:nonnumeric", False),
        (None, False),
        (1234, False),
        ("x" * 150 + ":4321", False),
    ],
)
def test_strict_mdns_endpoint_validation(value: Any, valid: bool) -> None:
    assert _endpoint_valid(value) is valid


def test_route_parse_accepts_only_exact_serial_and_tcp_port_range() -> None:
    good = (
        "FIXTURE-01 tcp:1234 tcp:4444\n"
        "FIXTURE-02 tcp:1111 tcp:2222\n"
        "FIXTURE-01 localabstract:secret tcp:3333\n"
        "FIXTURE-01 tcp:99999 tcp:4444\n"
        "FIXTURE-01 tcp:1234 tcp:99999\n"
        "FIXTURE-01 tcp:0 tcp:8888\n"
        "FIXTURE-01 tcp:3444\n"
    )
    parsed, bad = _routes(good, "FIXTURE-01", "forward")
    assert bad is True
    assert parsed == [{"direction": "forward", "local_port": 1234, "remote_port": 4444}]
    assert "secret" not in str(parsed)
    long = "".join(f"FIXTURE-01 tcp:{n + 3000} tcp:5000\n" for n in range(MAX_ROUTES + 2))
    trimmed, bad = _routes(long, "FIXTURE-01", "reverse")
    assert bad and len(trimmed) == MAX_ROUTES
    assert trimmed[-1] == {
        "direction": "reverse",
        "local_port": 3000 + MAX_ROUTES - 1,
        "remote_port": 5000,
    }


def test_mdns_rejects_tainted_rows_bounds_count_and_does_not_leak_endpoints() -> None:
    mdns = (
        "List of discovered mdns services\n"
        "OK._adb-tls-connect._tcp. 10.20.30.40:4444\n"
        "BAD.service 10.20.30.41:4444\n"
        "BAD._adb-tls-connect._tcp. token:SECRET\n"
        "MALFORMED_ONLY\n"
    )
    value, bad = _mdns(mdns, "10.20.30.40:4444")
    assert bad is True
    assert value == {"service_count": 1, "endpoint_found": True}
    assert "10.20" not in json.dumps(value)
    services = "".join(
        f"N{n}._adb-tls-pairing._tcp. 192.168.0.1:{4000 + n}\n"
        for n in range(MAX_MDNS_SERVICES + 1)
    )
    value, bad = _mdns(services, "192.168.0.1:4000")
    assert bad and value["service_count"] == MAX_MDNS_SERVICES
    value, bad = _mdns(
        "List of discovered mDNS services\nNAME._adb-tls-pairing._tcp. [::1]:9444\n", None
    )
    assert not bad
    assert value == {"service_count": 1, "endpoint_found": None}


def test_unfamiliar_discovery_error_is_canonicalized() -> None:
    response = run(report(error=Diagnostic("UNKNOWN_PRIVATE_TRACE", "TOKEN_ABCDEF")))
    assert codes(response) == ["ADB_INSPECT_FAILED"]
    assert "TOKEN_ABCDEF" not in json.dumps(response)


def test_nonready_states_are_not_implicitly_selected_or_reconnected() -> None:
    for state in ("sideload", "bootloader", "rescue"):
        fake = Fake(report(state=state))
        transport = AdbTransport(adb=fake)  # type: ignore[arg-type]
        response = transport.inspect(device_id="FIXTURE-01", transport_id="7", wait_seconds=2.0)
        assert response["status"] == "error" and codes(response) == ["DEVICE_NOT_READY"]
        assert fake.calls == 1
    pending = run(report(state="offline"))
    assert pending["status"] == "pending" and codes(pending) == ["WAIT_TIMEOUT"]
    assert pending["observed_state"] == "offline"
    assert pending["routes"] == []


def test_recovery_target_is_inspectable_only_by_explicit_state() -> None:
    denied = run(report(state="recovery"))
    assert denied["status"] == "pending"
    ready = run(report(state="recovery"), target_state="recovery")
    assert ready["status"] == "ok"
    assert ready["observed_state"] == "recovery"


def test_cancellation_preceding_discovery_or_after_ready_skips_all_routes() -> None:
    cancelled = threading.Event()
    cancelled.set()
    fake = Fake(report())
    reader = Runner()
    service = AdbTransport(adb=fake, runner=reader)  # type: ignore[arg-type]
    early = service.inspect(device_id="FIXTURE-01", transport_id="7", cancel=cancelled)
    assert early["status"] == "cancelled" and codes(early) == ["CANCELLED"]
    assert fake.calls == 0 and reader.calls == []

    class CancelAfterInspect(Fake):
        def inspect(self) -> AdbReport:
            result = super().inspect()
            cancelled.set()
            return result

    cancelled.clear()
    fake2 = CancelAfterInspect(report())
    late = AdbTransport(adb=fake2, runner=reader).inspect(  # type: ignore[arg-type]
        device_id="FIXTURE-01", transport_id="7", include_routes=True, cancel=cancelled
    )
    assert late["status"] == "cancelled" and codes(late) == ["CANCELLED"]
    assert reader.calls == []


def test_cancel_between_forward_and_reverse_stops_further_process_dispatch() -> None:
    cancelled = threading.Event()
    reader = Runner()

    def cancel_after_forward(
        argv: Sequence[str], timeout_s: float, byte_limit: int
    ) -> subprocess.CompletedProcess[str]:
        reader.calls.append(list(argv))
        cancelled.set()
        return subprocess.CompletedProcess(argv, 0, "FIXTURE-01 tcp:1234 tcp:5678\n", "")

    service = AdbTransport(adb=Fake(report()), runner=cancel_after_forward)  # type: ignore[arg-type]
    response = service.inspect(
        device_id="FIXTURE-01", transport_id="7", include_routes=True, cancel=cancelled
    )
    assert response["status"] == "cancelled"
    assert len(response["routes"]) == 1
    assert reader.calls == [["/fake/adb", "-s", "FIXTURE-01", "forward", "--list"]]


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (subprocess.TimeoutExpired(["fake"], 1), "timeout", "TRANSPORT_TIMEOUT"),
        (OutputLimitExceeded("private contents"), "partial", "OUTPUT_LIMIT"),
        (OSError("private stderr"), "partial", "TRANSPORT_EXEC_FAILED"),
    ],
)
@pytest.mark.parametrize("mdns", [False, True])
def test_command_errors_preserve_typed_bounded_outcomes(
    failure: BaseException, status: str, code: str, mdns: bool
) -> None:
    reader = Runner([failure])
    reply = run(
        report(),
        reader=reader,
        include_routes=not mdns,
        include_mdns=mdns,
    )
    assert reply["status"] == status and codes(reply) == [code]
    assert "private" not in str(reply)
    if mdns:
        assert reader.calls == [["/fake/adb", "mdns", "services"]]
    else:
        assert reader.calls == [["/fake/adb", "-s", "FIXTURE-01", "forward", "--list"]]


@pytest.mark.parametrize("mdns", [False, True])
def test_nonzero_exit_is_partial_without_echoing_child_stderr(mdns: bool) -> None:
    reader = Runner([subprocess.CompletedProcess(["fake"], 7, "", "Bearer SECRET_XX")])
    reply = run(report(), reader=reader, include_routes=not mdns, include_mdns=mdns)
    assert reply["status"] == "partial"
    assert codes(reply) == ["TRANSPORT_COMMAND_FAILED"]
    assert "SECRET" not in str(reply)


def test_nonempty_stderr_is_typed_partial_without_raw_stderr_or_routes() -> None:
    reader = Runner(
        [
            subprocess.CompletedProcess(
                ["fake"], 0, "FIXTURE-01 tcp:1234 tcp:5678\n", "token=secret"
            ),
            subprocess.CompletedProcess(["fake"], 0, "", ""),
        ]
    )
    reply = run(report(), reader=reader, include_routes=True)
    assert reply["status"] == "partial"
    assert codes(reply) == ["MALFORMED_ROUTE"]
    assert "token" not in str(reply)
    assert len(reply["routes"]) == 1


def test_mdns_success_and_no_exact_match_is_truthful() -> None:
    reader = Runner(
        [
            subprocess.CompletedProcess(
                ["fake"], 0, "fixture._adb-tls-connect._tcp. 192.168.0.5:9999\n", ""
            )
        ]
    )
    reply = run(report(), reader=reader, include_mdns=True, mdns_endpoint="192.168.0.6:9999")
    assert reply["status"] == "ok"
    assert reply["mdns"] == {"service_count": 1, "endpoint_found": False}


def test_missing_binary_for_routes_never_falls_back_to_path() -> None:
    reader = Runner()
    reply = run(report(executable=None), reader=reader, include_routes=True)
    assert reply["status"] == "error" and codes(reply) == ["ADB_NOT_FOUND"]
    assert reader.calls == []


def test_output_route_limit_caps_combined_forward_and_reverse_entries() -> None:
    batch = "".join(f"FIXTURE-01 tcp:{2000 + x} tcp:4444\n" for x in range(MAX_ROUTES))
    reader = Runner(
        [
            subprocess.CompletedProcess(["fake"], 0, batch, ""),
            subprocess.CompletedProcess(["fake"], 0, "FIXTURE-01 tcp:7777 tcp:8888\n", ""),
        ]
    )
    reply = run(report(), reader=reader, include_routes=True)
    assert reply["status"] == "partial"
    assert len(reply["routes"]) == MAX_ROUTES
    assert codes(reply) == ["MALFORMED_ROUTE"]


def test_schema_failclosed_if_a_packaged_resource_is_not_a_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import android_mcp_host.adb_transport as transport

    class Resource:
        def joinpath(self, _: str) -> Resource:
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(transport, "files", lambda _: Resource())
    with pytest.raises(ValueError, match="Invalid packaged"):
        get_transport_output_schema()


def test_async_cancelled_mcp_call_sets_cooperative_stop_event() -> None:
    started = threading.Event()
    stopped = threading.Event()

    class BlockingTransport:
        def inspect(self, **kwargs: Any) -> dict[str, Any]:
            started.set()
            event: threading.Event = kwargs["cancel"]
            if event.wait(timeout=3):
                stopped.set()
            return {}

    async def scenario() -> None:
        from android_mcp_host.server import create_server

        async with Client(create_server(adb_transport=BlockingTransport())) as client:  # type: ignore[arg-type]
            task = asyncio.create_task(
                client.call_tool(
                    "adb_transport_inspect",
                    {"device_id": "FIXTURE-01", "transport_id": "7"},
                )
            )
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await asyncio.to_thread(stopped.wait, 2)

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [[], {}, ["device"], 17])
def test_unhashable_target_state_returns_typed_denial_before_any_adb(
    value: Any,
) -> None:
    source = Fake(report())
    runner = Runner()
    service = AdbTransport(adb=source, runner=runner)  # type: ignore[arg-type]
    result = service.inspect(device_id="FIXTURE-01", transport_id="7", target_state=value)
    assert result["status"] == "error"
    assert codes(result) == ["INVALID_TARGET_STATE"]
    assert source.calls == 0 and runner.calls == []


@pytest.mark.parametrize("mdns", [False, True])
def test_even_host_injected_malicious_runner_output_is_checked_against_64k(
    mdns: bool,
) -> None:
    reader = Runner([subprocess.CompletedProcess(["fixture"], 0, "x" * 70000, "sensitive stderr")])
    result = run(report(), reader=reader, include_routes=not mdns, include_mdns=mdns)
    assert result["status"] == "partial"
    assert codes(result) == ["OUTPUT_LIMIT"]
    assert "sensitive" not in str(result)


@pytest.mark.parametrize("fault", [ValueError("private"), RuntimeError("private")])
@pytest.mark.parametrize("mdns", [False, True])
def test_unexpected_host_adapter_failures_are_typed_and_redacted(
    fault: Exception, mdns: bool
) -> None:
    reader = Runner([fault])
    result = run(report(), reader=reader, include_routes=not mdns, include_mdns=mdns)
    assert result["status"] == "partial"
    assert codes(result) == ["TRANSPORT_EXEC_FAILED"]
    assert "private" not in str(result)

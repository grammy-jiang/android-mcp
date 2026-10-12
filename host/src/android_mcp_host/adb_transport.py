"""Target-pinned, read-only ADB transport wait and forwarding/mDNS inspection.

No pairing, connect/disconnect, port creation, raw shell, device mutation or
client-supplied executable is provided. Polls are finite and each subprocess
uses the existing bounded, process-group-managed execution primitive.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any

from android_mcp_host.adb import AdbClient, AdbReport, Device, valid_device_serial
from android_mcp_host.command_runner import OutputLimitExceeded, completed_bounded

MAX_WAIT_SECONDS = 10.0
MAX_ROUTES = 32
MAX_MDNS_SERVICES = 32
OUTPUT_BYTES = 65536
_TRANSPORT = re.compile(r"[1-9][0-9]{0,9}\Z", re.ASCII)
_TCP = re.compile(r"tcp:([1-9][0-9]{0,4})\Z", re.ASCII)
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,126}\Z", re.ASCII)
_SERVICE = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z", re.ASCII)
_ALLOWED_SERVICE_SUFFIXES = ("._adb-tls-connect._tcp.", "._adb-tls-pairing._tcp.")
_ERRORS = frozenset(
    {"ADB_NOT_FOUND", "ADB_TIMEOUT", "ADB_OUTPUT_LIMIT", "ADB_EXEC_FAILED", "ADB_LIST_FAILED"}
)
_READ_STATES = frozenset({"device", "recovery"})
Runner = Callable[[Sequence[str], float, int], subprocess.CompletedProcess[str]]


def get_transport_output_schema() -> dict[str, Any]:
    """Load the Host-only v1 transport envelope packaged in the wheel."""
    value: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-adb-transport.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged ADB transport schema")
    return value


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": "Selected ADB transport could not be safely inspected"}


def _endpoint_valid(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 145 or ":" not in value:
        return False
    host, _, port = value.rpartition(":")
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        return False
    if host.startswith("[") and host.endswith("]"):
        # Scoped IPv6 zone identifiers are Host-local interfaces, not valid
        # remote mDNS endpoints; never accept or reflect those caller strings.
        if "%" in host:
            return False
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return False
        return True
    if not _HOST.fullmatch(host) or ".." in host or host.endswith("."):
        return False
    if any(part.startswith("-") or part.endswith("-") for part in host.split(".")):
        return False
    # Reject unqualified names and malformed numeric pseudo-IP addresses.
    if "." not in host:
        return False
    if all(character in "0123456789." for character in host):
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            return False
    return True


def _routes(stdout: str, serial: str, direction: str) -> tuple[list[dict[str, Any]], bool]:
    routes: list[dict[str, Any]] = []
    invalid = False
    for raw in stdout.splitlines():
        parts = raw.split()
        if len(parts) != 3 or parts[0] != serial:
            invalid = True
            continue
        local, remote = _TCP.fullmatch(parts[1]), _TCP.fullmatch(parts[2])
        if local is None or remote is None:
            invalid = True
            continue
        source, destination = int(local.group(1)), int(remote.group(1))
        if source > 65535 or destination > 65535:
            invalid = True
            continue
        if len(routes) >= MAX_ROUTES:
            return routes, True
        routes.append(
            {
                "direction": direction,
                "local_port": source,
                "remote_port": destination,
            }
        )
    return routes, invalid


def _mdns(stdout: str, selected_endpoint: str | None) -> tuple[dict[str, Any], bool]:
    count = 0
    found = False
    invalid = False
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(
            ("List of discovered mdns services", "List of discovered mDNS services")
        ):
            continue
        pieces = line.split()
        if (
            len(pieces) != 2
            or not _SERVICE.fullmatch(pieces[0])
            or not pieces[0].endswith(_ALLOWED_SERVICE_SUFFIXES)
            or not _endpoint_valid(pieces[1])
        ):
            invalid = True
            continue
        if count >= MAX_MDNS_SERVICES:
            invalid = True
            break
        count += 1
        found = found or pieces[1] == selected_endpoint
    return {"service_count": count, "endpoint_found": found if selected_endpoint else None}, invalid


class AdbTransport:
    """A bounded read-only transport check, requiring serial AND transport ID."""

    def __init__(
        self,
        adb: AdbClient | None = None,
        *,
        runner: Runner = completed_bounded,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._adb = adb if adb is not None else AdbClient()
        self._runner = runner
        self._clock = clock
        self._sleeper = sleeper

    @staticmethod
    def _selected(
        report: AdbReport, device_id: str, transport_id: str
    ) -> tuple[Device | None, str | None]:
        if report.error is not None:
            code = report.error.code
            return None, code if code in _ERRORS else "ADB_INSPECT_FAILED"
        if not report.available:
            return None, "ADB_NOT_FOUND"
        matching = [device for device in report.devices if device.device_id == device_id]
        if not matching:
            return None, "DEVICE_NOT_FOUND"
        if len(matching) != 1:
            return None, "AMBIGUOUS_DEVICE_ID"
        selected = matching[0]
        duplicates = [
            device
            for device in report.devices
            if device.properties.get("transport_id") == transport_id
        ]
        if len(duplicates) > 1:
            return None, "AMBIGUOUS_TRANSPORT_ID"
        if selected.properties.get("transport_id") != transport_id:
            return None, "STALE_TRANSPORT_ID"
        if selected.state in {"unauthorized", "authorizing", "no_permissions"}:
            return None, "DEVICE_NOT_READY"
        return selected, None

    def inspect(
        self,
        *,
        device_id: str,
        transport_id: str,
        target_state: str = "device",
        wait_seconds: float = 0.0,
        include_routes: bool = False,
        include_mdns: bool = False,
        mdns_endpoint: str | None = None,
        cancel: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Observe exact identity, optionally polling for a finite time.

        The result is NOT permission to interact with a device. mDNS endpoints
        are only used for exact local filtering; never reflected in output.
        """
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "device_id": device_id if valid_device_serial(device_id) else "",
            "transport_id": transport_id
            if isinstance(transport_id, str) and _TRANSPORT.fullmatch(transport_id)
            else None,
            "observed_state": None,
            "status": "error",
            "routes": [],
            "mdns": None,
            "errors": [],
        }

        def fail(code: str, status: str = "error") -> dict[str, Any]:
            response["status"] = status
            response["errors"].append(_error(code))
            return response

        if (
            not valid_device_serial(device_id)
            or not isinstance(transport_id, str)
            or not _TRANSPORT.fullmatch(transport_id)
        ):
            return fail("INVALID_TARGET")
        if target_state not in _READ_STATES:
            return fail("INVALID_TARGET_STATE")
        if (
            type(wait_seconds) not in (int, float)
            or not math.isfinite(wait_seconds)
            or not 0 <= wait_seconds <= MAX_WAIT_SECONDS
        ):
            return fail("INVALID_WAIT")
        if type(include_routes) is not bool or type(include_mdns) is not bool:
            return fail("INVALID_OPTIONS")
        if mdns_endpoint is not None and (not include_mdns or not _endpoint_valid(mdns_endpoint)):
            return fail("INVALID_MDNS_ENDPOINT")
        if cancel is not None and cancel.is_set():
            return fail("CANCELLED", "cancelled")

        deadline = self._clock() + wait_seconds
        report = self._adb.inspect()
        selected, error = self._selected(report, device_id, transport_id)
        if error is not None:
            return fail(error)
        assert selected is not None
        response["observed_state"] = selected.state
        while selected.state != target_state:
            if cancel is not None and cancel.is_set():
                return fail("CANCELLED", "cancelled")
            if selected.state not in {"offline", "recovery"}:
                return fail("DEVICE_NOT_READY")
            remaining = deadline - self._clock()
            if remaining <= 0:
                return fail("WAIT_TIMEOUT", "timeout" if wait_seconds else "pending")
            self._sleeper(min(0.25, remaining))
            if cancel is not None and cancel.is_set():
                return fail("CANCELLED", "cancelled")
            report = self._adb.inspect()
            selected, error = self._selected(report, device_id, transport_id)
            if error is not None:
                if error == "DEVICE_NOT_FOUND":
                    return fail("DISCONNECTED")
                return fail(error)
            assert selected is not None
            response["observed_state"] = selected.state

        if cancel is not None and cancel.is_set():
            return fail("CANCELLED", "cancelled")
        if include_routes or include_mdns:
            binary = report.executable
            if not binary:
                return fail("ADB_NOT_FOUND")
            if include_routes:
                for direction in ("forward", "reverse"):
                    if cancel is not None and cancel.is_set():
                        return fail("CANCELLED", "cancelled")
                    try:
                        outcome = self._runner(
                            [binary, "-s", device_id, direction, "--list"], 3.0, OUTPUT_BYTES
                        )
                    except subprocess.TimeoutExpired:
                        return fail("TRANSPORT_TIMEOUT", "timeout")
                    except OutputLimitExceeded:
                        return fail("OUTPUT_LIMIT", "partial")
                    except OSError:
                        return fail("TRANSPORT_EXEC_FAILED", "partial")
                    if outcome.returncode != 0:
                        return fail("TRANSPORT_COMMAND_FAILED", "partial")
                    parsed, invalid = _routes(outcome.stdout, device_id, direction)
                    room = MAX_ROUTES - len(response["routes"])
                    response["routes"].extend(parsed[:room])
                    if outcome.stderr or len(parsed) > room or invalid:
                        response["errors"].append(_error("MALFORMED_ROUTE"))
            if include_mdns:
                try:
                    outcome = self._runner([binary, "mdns", "services"], 3.0, OUTPUT_BYTES)
                except subprocess.TimeoutExpired:
                    return fail("TRANSPORT_TIMEOUT", "timeout")
                except OutputLimitExceeded:
                    return fail("OUTPUT_LIMIT", "partial")
                except OSError:
                    return fail("TRANSPORT_EXEC_FAILED", "partial")
                if outcome.returncode != 0:
                    return fail("TRANSPORT_COMMAND_FAILED", "partial")
                response["mdns"], invalid = _mdns(outcome.stdout, mdns_endpoint)
                if invalid or outcome.stderr:
                    response["errors"].append(_error("MALFORMED_MDNS_ROW"))
        response["status"] = "partial" if response["errors"] else "ok"
        return response

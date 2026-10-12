"""H0.c: safe profile selection, 95-family inventory and ephemeral target hints."""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.server import create_server

DEVICE = "H0C-SYNTHETIC-01"
TRANSPORT = "7"
CATALOG = (
    Path(__file__).resolve().parents[2] / "docs/android-toolchain-capability-catalog-20261012.md"
)


class FakeInventory:
    def __init__(self, **available: bool) -> None:
        self.available = available
        self.calls = 0

    def inspect(self) -> dict[str, object]:
        self.calls += 1
        return {
            "schema_version": 1,
            "runtime": "host",
            "status": "partial",
            "tools": {
                name: {
                    "available": self.available.get(name, False),
                    "runnable": self.available.get(name, False),
                    "version": "synthetic" if self.available.get(name, False) else None,
                    "reason": "OK" if self.available.get(name, False) else "NOT_INSTALLED",
                }
                for name in ("adb", "fastboot", "java", "gradle", "sdk")
            },
        }


class FakeAdb:
    def __init__(self, state: str = "device", transport: str = TRANSPORT) -> None:
        self.state = state
        self.transport = transport
        self.calls = 0

    def inspect(self) -> AdbReport:
        self.calls += 1
        return AdbReport(
            True,
            "/synthetic/adb",
            "37.0.1",
            None,
            (Device(DEVICE, self.state, {"transport_id": self.transport}),),
        )


def _profiles(*names: str, inventory: FakeInventory | None = None) -> Any:
    from android_mcp_host.capability_profiles import CapabilityProfiles

    return CapabilityProfiles(
        profile_ids=names or ("safe",),
        toolchain=inventory or FakeInventory(),
    )


def _family(profile: Any, family_id: str) -> dict[str, Any]:
    state: dict[str, Any] = profile.capability(family_id)
    return state


def test_t_h0c_01_default_only_d0_and_no_physical_mutation() -> None:
    profile = _profiles("safe", inventory=FakeInventory(adb=True, sdk=True, fastboot=True))
    document = profile.snapshot()
    assert document["schema_version"] == 1
    assert document["runtime"] == "host"
    assert document["profile"] == "safe"
    assert document["mutation_enabled"] is False
    assert document["target_authority"] is False
    assert len(document["capabilities"]) > 0
    assert all(record["risk"] == "D0" for record in document["capabilities"])
    runnable = {
        record["catalog_id"] for record in document["capabilities"] if record["state"] == "runnable"
    }
    assert runnable <= {"A01", "A02", "H01"}
    assert "A01" in runnable
    for family_id in ("A22", "A25", "A37", "F07", "F09", "R07"):
        assert _family(profile, family_id)["authorized"] is False
        assert _family(profile, family_id)["state"] != "runnable"


def test_t_h0c_02_missing_local_cli_or_provider_remains_unavailable() -> None:
    profile = _profiles("diagnostic", inventory=FakeInventory(adb=True))
    assert _family(profile, "H01")["state"] == "unavailable"
    assert _family(profile, "H01")["reason"] == "NOT_INSTALLED"
    assert _family(profile, "F01")["state"] == "unavailable"
    assert _family(profile, "F01")["reason"] == "NOT_INSTALLED"
    assert _family(profile, "E03")["state"] == "unavailable"
    assert _family(profile, "E03")["reason"] == "PROVIDER_NOT_CONNECTED"
    assert _family(profile, "H02")["authorized"] is False
    with_installed = _profiles(
        "diagnostic", inventory=FakeInventory(adb=True, sdk=True, fastboot=True)
    )
    assert _family(with_installed, "F01")["state"] == "plan_only"
    assert _family(with_installed, "F01")["authorized"] is False
    assert _family(with_installed, "H02")["state"] != "runnable"
    assert _family(with_installed, "E03")["state"] == "unavailable"


@pytest.mark.parametrize(
    "profiles",
    [
        ("safe", "safe"),
        ("safe", "diagnostic"),
        ("unknown",),
        ("developer",),
        ("all",),
        ("SAFE",),
        ("safe ",),
        (),
    ],
)
def test_t_h0c_03_invalid_duplicate_and_conflicting_profiles_denied(
    profiles: tuple[str, ...],
) -> None:
    from android_mcp_host.capability_profiles import CapabilityProfiles

    with pytest.raises(ValueError):
        CapabilityProfiles(profile_ids=profiles, toolchain=FakeInventory())


def test_t_h0c_04_temp_target_reference_stales_and_is_never_a_lease() -> None:
    from android_mcp_host.capability_profiles import TargetHintRegistry

    now = [100.0]
    registry = TargetHintRegistry(clock=lambda: now[0], ttl_s=20.0)
    report = FakeAdb().inspect()
    hint = registry.issue(report, device_id=DEVICE, transport_id=TRANSPORT)
    assert hint["kind"] == "observation_only"
    assert hint["authorization"] == "none"
    assert hint["target_ref"].isascii()
    assert DEVICE not in hint["target_ref"]
    assert registry.validate(hint["target_ref"], report) is True
    now[0] += 21
    assert registry.validate(hint["target_ref"], report) is False

    now[0] += 1
    changed = registry.issue(report, device_id=DEVICE, transport_id=TRANSPORT)
    altered = FakeAdb(transport="8").inspect()
    assert registry.validate(changed["target_ref"], altered) is False
    # A changed/rejected reference cannot become valid again by reconnecting.
    assert registry.validate(changed["target_ref"], report) is False

    ref = registry.issue(report, device_id=DEVICE, transport_id=TRANSPORT)
    assert registry.validate(ref["target_ref"], FakeAdb(state="offline").inspect()) is False
    assert registry.validate(ref["target_ref"], report) is False

    for bad_id, bad_tid in (("-s", TRANSPORT), (DEVICE, "8"), ("OTHER", TRANSPORT)):
        with pytest.raises(ValueError):
            registry.issue(report, device_id=bad_id, transport_id=bad_tid)
    duplicate = AdbReport(True, "/synthetic/adb", "37", None, report.devices * 2)
    with pytest.raises(ValueError):
        registry.issue(duplicate, device_id=DEVICE, transport_id=TRANSPORT)
    assert registry.validate("not-issued-ref", report) is False


def test_t_h0c_05_all_95_host_families_exactly_once_and_upgrade_protected() -> None:
    from android_mcp_host.capability_profiles import load_ledger, validate_ledger

    text = CATALOG.read_text(encoding="utf-8")
    catalog_ids = re.findall(r"^\| ([AHFPRE][0-9]{2}) \|", text, re.MULTILINE)
    assert len(catalog_ids) == 95 and len(set(catalog_ids)) == 95
    assert len(re.findall(r"^\| N[0-9]{2} \|", text, re.MULTILINE)) == 20
    ledger = load_ledger()
    assert [entry["catalog_id"] for entry in ledger] == sorted(catalog_ids)
    validate_ledger(ledger)
    assert all(entry["owner"] == "host" for entry in ledger)
    assert all(
        entry["disposition"] != "runnable"
        or entry["catalog_id"]
        in {
            "A01",
            "A02",
            "H01",
        }
        for entry in ledger
    )
    for removed_or_duplicated in (ledger[:-1], ledger + [ledger[-1]]):
        with pytest.raises(ValueError):
            validate_ledger(removed_or_duplicated)
    mutated = deepcopy(ledger)
    next(entry for entry in mutated if entry["catalog_id"] == "F07")["disposition"] = "runnable"
    with pytest.raises(ValueError):
        validate_ledger(mutated)
    mutated = deepcopy(ledger)
    next(entry for entry in mutated if entry["catalog_id"] == "A22")["disposition"] = (
        "implemented_read_only"
    )
    with pytest.raises(ValueError):
        validate_ledger(mutated)


def test_t_h0c_06_opt_in_real_mcp_schema_http_and_legacy_tools_unchanged(
    tmp_path: Path,
) -> None:
    # RED PHASE: before implementing this package, create_server rejects the
    # new keyword argument. This tests public registration, not module import.
    class StubProfiles:
        def snapshot(self) -> dict[str, object]:
            return {
                "schema_version": 1,
                "runtime": "host",
                "profile": "safe",
                "mutation_enabled": False,
                "target_authority": False,
                "capabilities": [],
            }

    async def in_process() -> None:
        adb = FakeAdb()
        async with Client(create_server(adb=adb)) as old:
            previous = {t.name: t for t in await old.list_tools()}
            before = await old.call_tool("device_status", {})
        async with Client(create_server(adb=adb, capability_profiles=StubProfiles())) as client:  # type: ignore[call-arg]
            after_catalog = {t.name: t for t in await client.list_tools()}
            assert set(after_catalog) == {*previous, "host_capability_profile"}
            for name, baseline_tool in previous.items():
                updated = after_catalog[name]
                assert (
                    updated.title,
                    updated.description,
                    updated.annotations,
                    updated.input_schema,
                    updated.output_schema,
                ) == (
                    baseline_tool.title,
                    baseline_tool.description,
                    baseline_tool.annotations,
                    baseline_tool.input_schema,
                    baseline_tool.output_schema,
                )
            tool = after_catalog["host_capability_profile"]
            assert tool.input_schema.get("required", []) == []
            assert not tool.input_schema.get("properties")
            assert tool.output_schema is not None
            assert tool.output_schema["$id"] == "urn:android-mcp:host-capability-profile:v1"
            assert tool.annotations is not None
            hints = tool.annotations.model_dump(mode="json", by_alias=True)
            assert hints["readOnlyHint"] is False  # live fixed-CLI probes may affect Host caches
            assert hints["destructiveHint"] is False
            assert hints["openWorldHint"] is False
            Draft202012Validator.check_schema(tool.output_schema)
            result = await client.call_tool("host_capability_profile", {})
            assert not result.is_error
            assert isinstance(result.structured_content, dict)
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            assert result.structured_content["mutation_enabled"] is False
            latest = await client.call_tool("device_status", {})
            assert before.structured_content == latest.structured_content

    asyncio.run(in_process())

    # Host-only loopback HTTP test with a fake profile provider. No ADB needed.
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = (
        "import sys\nfrom android_mcp_host.server import create_server\n"
        "class Profiles:\n"
        " def snapshot(self):\n"
        "  return {'schema_version':1,'runtime':'host','profile':'safe',"
        "'mutation_enabled':False,'target_authority':False,'capabilities':[]}\n"
        "create_server(capability_profiles=Profiles()).run("
        "transport='http',host='127.0.0.1',port=int(sys.argv[1]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def check_http() -> None:
        last: Exception | None = None
        for _ in range(50):
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp/") as client:
                    catalog = {t.name: t for t in await client.list_tools()}
                    assert "host_capability_profile" in catalog
                    reply = await client.call_tool("host_capability_profile", {})
                    assert not reply.is_error
                    assert isinstance(reply.structured_content, dict)
                    Draft202012Validator(catalog["host_capability_profile"].output_schema).validate(
                        reply.structured_content
                    )
                    assert reply.structured_content["profile"] == "safe"
                    return
            except Exception as error:
                last = error
                await asyncio.sleep(0.1)
        raise AssertionError(f"Synthetic profile localhost HTTP failed: {last!r}")

    try:
        asyncio.run(check_http())
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    assert process.poll() is not None

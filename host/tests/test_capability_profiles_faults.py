"""H0.c adversarial catalog/provider and time-bounded target-hint regression."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import android_mcp_host.capability_profiles as cp
from android_mcp_host.adb import AdbReport, Device, Diagnostic

DEVICE = "SYNTHETIC-REF-01"
TID = "9"


def _report(state: str = "device", transport: str = TID) -> AdbReport:
    return AdbReport(
        True,
        "/synthetic/adb",
        "37",
        None,
        (Device(DEVICE, state, {"transport_id": transport}),),
    )


def _ledger_changed(family_id: str, **changes: Any) -> list[dict[str, Any]]:
    ledger = copy.deepcopy(cp.load_ledger())
    row = next(item for item in ledger if item["catalog_id"] == family_id)
    row.update(changes)
    return ledger


@pytest.mark.parametrize("value", [None, {}, "A01", 42, []])
def test_ledger_requires_precise_list_size(value: object) -> None:
    with pytest.raises(ValueError, match="95"):
        cp.validate_ledger(value)


def test_ledger_rejects_corrupt_shape_order_and_id() -> None:
    data = cp.load_ledger()
    data[0] = []
    with pytest.raises(ValueError, match="objects"):
        cp.validate_ledger(data)
    data = cp.load_ledger()
    data[1]["catalog_id"] = data[0]["catalog_id"]
    with pytest.raises(ValueError, match="duplicate"):
        cp.validate_ledger(data)
    data = cp.load_ledger()
    data.reverse()
    with pytest.raises(ValueError, match="unordered"):
        cp.validate_ledger(data)


@pytest.mark.parametrize(
    ("family_id", "changes", "message"),
    [
        ("A01", {"risk": "W3"}, "read-only"),
        ("A01", {"risk": "hazard"}, "risk"),
        ("A01", {"owner": "native"}, "owner"),
        ("A01", {"provider": "random-shell"}, "provider"),
        ("A01", {"disposition": "runnable"}, "disposition"),
        ("A37", {"disposition": "plan_only"}, "X5"),
        ("A03", {"disposition": "excluded_by_security"}, "excluded"),
        ("A01", {"disposition": "plan_only"}, "lost"),
        ("A03", {"disposition": "implemented_read_only"}, "upgrade"),
        ("A03", {"disposition": "implemented_disabled"}, "disabled"),
        ("A22", {"disposition": "plan_only"}, "Mutation preview"),
        ("A01", {"test_ids": []}, "evidence"),
        ("A01", {"merged_sha": None}, "merged"),
        ("A03", {"merged_sha": "a" * 40}, "cannot claim"),
        ("A03", {"verification": "verified_local"}, "cannot claim"),
    ],
)
def test_privilege_upgrade_or_fake_evidence_fails_closed(
    family_id: str, changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        cp.validate_ledger(_ledger_changed(family_id, **changes))


def test_non_object_schema_resource_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "[]"

    monkeypatch.setattr(cp, "_resource", lambda _: Fake())
    with pytest.raises(ValueError, match="JSON object"):
        cp.get_capability_output_schema()


@pytest.mark.parametrize(
    "providers",
    [frozenset({"unknown-provider"}), {"play"}, frozenset({"play", "unknown"})],
)
def test_only_approved_host_managed_provider_config(providers: Any) -> None:
    with pytest.raises(ValueError, match="provider"):
        cp.CapabilityProfiles(connected_providers=providers)


def test_diagnostic_requires_target_but_local_available_d0_is_truthful() -> None:
    class Inventory:
        def __init__(self) -> None:
            self.calls = 0

        def inspect(self) -> dict[str, object]:
            self.calls += 1
            return {
                "runtime": "host",
                "tools": {
                    "adb": {"runnable": True, "reason": "OK"},
                    "fastboot": {"runnable": False, "reason": "TIMEOUT"},
                    "sdk": {"runnable": True, "reason": "OK"},
                },
            }

    source = Inventory()
    service = cp.CapabilityProfiles(
        profile_ids=("diagnostic",), toolchain=source, inventory_enabled=True
    )
    data = service.snapshot()
    assert source.calls == 1  # shared snapshot, not one external probe per family
    Draft202012Validator(cp.get_capability_output_schema()).validate(data)
    assert service.capability("A10") == {
        "catalog_id": "A10",
        "risk": "D1",
        "state": "requires_target",
        "reason": "EXPLICIT_TARGET_REQUIRED",
        "authorized": False,
    }
    assert service.capability("F01")["reason"] == "TIMEOUT"
    assert service.capability("H01")["state"] == "runnable"
    assert service.capability("E03")["authorized"] is False


def test_connected_external_provider_does_not_enable_unimplemented_api() -> None:
    service = cp.CapabilityProfiles(
        profile_ids=("diagnostic",), connected_providers=frozenset({"play"})
    )
    result = service.capability("E03")
    assert result["state"] == "plan_only"
    assert result["reason"] == "NOT_IMPLEMENTED"
    assert result["authorized"] is False
    with pytest.raises(ValueError, match="Unknown"):
        service.capability("N01")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"runtime": "native", "tools": {"adb": {"runnable": True}}},
        {"runtime": "host", "tools": "not a mapping"},
    ],
)
def test_malformed_inventory_does_not_claim_runnable(bad: Any) -> None:
    class BrokenInventory:
        def inspect(self) -> Any:
            return bad

    service = cp.CapabilityProfiles(toolchain=BrokenInventory())
    assert service.capability("A01")["state"] == "unavailable"
    assert service.capability("A01")["reason"] == "NOT_INSTALLED"


@pytest.mark.parametrize(
    "exception", [OSError("secret"), RuntimeError("secret"), ValueError("secret")]
)
def test_inventory_probe_exception_is_bounded_and_fail_closed(exception: Exception) -> None:
    class BrokenInventory:
        def inspect(self) -> dict[str, object]:
            raise exception

    service = cp.CapabilityProfiles(toolchain=BrokenInventory())
    result = service.snapshot()
    assert all(entry["state"] != "runnable" for entry in result["capabilities"])
    assert "secret" not in str(result)


def test_missing_toolchain_source_and_invalid_boolean_do_not_enable() -> None:
    service = cp.CapabilityProfiles()
    assert service.capability("A01")["state"] == "unavailable"

    class FalsePositive:
        def inspect(self) -> dict[str, object]:
            return {"runtime": "host", "tools": {"adb": {"runnable": "yes", "reason": "OK"}}}

    service = cp.CapabilityProfiles(toolchain=FalsePositive())
    assert service.capability("A01")["reason"] == "NOT_INSTALLED"
    assert service.capability("A01")["authorized"] is False


@pytest.mark.parametrize("ttl", [0.0, -1.0, 61.0, float("nan")])
def test_invalid_ttl_cannot_extend_target_hint_indefinitely(ttl: float) -> None:
    with pytest.raises(ValueError, match="TTL"):
        cp.TargetHintRegistry(ttl_s=ttl)


@pytest.mark.parametrize("invalid", ["", "0", "0009", "12345678901", "9;reboot", "９"])
def test_invalid_transport_not_issued(invalid: str) -> None:
    registry = cp.TargetHintRegistry()
    with pytest.raises(ValueError, match="Unverified"):
        registry.issue(_report(), device_id=DEVICE, transport_id=invalid)


def test_error_or_absent_adb_report_cannot_authorize_target() -> None:
    registry = cp.TargetHintRegistry()
    for report in (
        AdbReport(False, None, None, None, _report().devices),
        AdbReport(True, "/synthetic/adb", "37", Diagnostic("E", "test"), _report().devices),
        AdbReport(True, "/synthetic/adb", "37", None, ()),
    ):
        with pytest.raises(ValueError):
            registry.issue(report, device_id=DEVICE, transport_id=TID)


def test_expiration_and_comparison_success_are_without_mutation_or_lease() -> None:
    now = [100.0]
    refs = cp.TargetHintRegistry(clock=lambda: now[0], ttl_s=3.0)
    created = refs.issue(_report(), device_id=DEVICE, transport_id=TID)
    assert refs.validate(created["target_ref"], _report())
    assert "none" == created["authorization"]
    assert set(created) == {"target_ref", "kind", "authorization"}
    now[0] += 3.0
    assert not refs.validate(created["target_ref"], _report())


def test_cli_configures_optional_profile_independently_of_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from android_mcp_host import cli

    calls: list[tuple[str, dict[str, Any]]] = []
    inventory = object()
    profile = object()

    class Server:
        def run(self, **kwargs: Any) -> None:
            calls.append(("run", kwargs))

    def profile_factory(**kwargs: Any) -> object:
        assert kwargs["profile_ids"] in {("safe",), ("diagnostic",)}
        assert kwargs["toolchain"] is inventory
        return profile

    def server_factory(**kwargs: Any) -> Server:
        calls.append(("create", kwargs))
        return Server()

    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "ToolchainInventory", lambda: inventory)
    monkeypatch.setattr(cli, "CapabilityProfiles", profile_factory)
    monkeypatch.setattr(cli, "create_server", server_factory)

    assert cli.main(["serve", "--capability-profile", "safe"]) == 0
    assert calls[0] == ("create", {"capability_profiles": profile})
    calls.clear()
    assert cli.main(["serve", "--toolchain-inventory", "--capability-profile", "diagnostic"]) == 0
    assert calls[0] == (
        "create",
        {"toolchain_inventory": inventory, "capability_profiles": profile},
    )


def test_cli_rejects_unapproved_profile_before_server_start() -> None:
    from android_mcp_host.cli import main

    with pytest.raises(SystemExit) as error:
        main(["serve", "--capability-profile", "developer"])
    assert error.value.code == 2


def test_toolchain_presence_is_not_tool_registration_authority() -> None:
    class Installed:
        def inspect(self) -> dict[str, object]:
            return {
                "runtime": "host",
                "tools": {"sdk": {"runnable": True, "reason": "OK"}},
            }

    default = cp.CapabilityProfiles(toolchain=Installed())
    assert default.capability("H01")["authorized"] is False
    assert default.capability("H01")["state"] == "not_exposed"

    enabled = cp.CapabilityProfiles(toolchain=Installed(), inventory_enabled=True)
    assert enabled.capability("H01")["state"] == "runnable"
    assert enabled.capability("H01")["authorized"] is True


def test_contradictory_toolchain_status_is_never_runnable() -> None:
    class Contradictory:
        def inspect(self) -> dict[str, object]:
            return {
                "runtime": "host",
                "tools": {"adb": {"runnable": True, "reason": "TIMEOUT"}},
            }

    result = cp.CapabilityProfiles(toolchain=Contradictory()).capability("A01")
    assert result["authorized"] is False
    assert result["state"] == "unavailable"


def test_manifest_risk_downgrade_without_review_is_rejected() -> None:
    with pytest.raises(ValueError, match="classification"):
        cp.validate_ledger(_ledger_changed("F07", risk="D0"))


def test_target_registry_caps_live_handles_and_prunes_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    generated = iter(f"{n:032x}" for n in range(400))
    monkeypatch.setattr(cp.secrets, "token_hex", lambda _: next(generated))
    registry = cp.TargetHintRegistry(clock=lambda: clock[0], ttl_s=1.0)
    for _ in range(128):
        registry.issue(_report(), device_id=DEVICE, transport_id=TID)
    with pytest.raises(ValueError, match="budget"):
        registry.issue(_report(), device_id=DEVICE, transport_id=TID)
    clock[0] += 2.0
    new_hint = registry.issue(_report(), device_id=DEVICE, transport_id=TID)
    assert registry.validate(new_hint["target_ref"], _report()) is True


def test_non_string_transport_fails_closed() -> None:
    registry = cp.TargetHintRegistry()
    with pytest.raises(ValueError, match="Unverified"):
        registry.issue(_report(), device_id=DEVICE, transport_id=None)  # type: ignore[arg-type]


def test_actual_profile_server_returns_typed_scoped_not_authorized_states() -> None:
    import asyncio

    from fastmcp import Client
    from jsonschema import Draft202012Validator

    from android_mcp_host.server import create_server

    class Installed:
        def inspect(self) -> dict[str, object]:
            return {
                "runtime": "host",
                "tools": {
                    "adb": {"runnable": True, "reason": "OK"},
                    "sdk": {"runnable": True, "reason": "OK"},
                },
            }

    async def check() -> None:
        profiles = cp.CapabilityProfiles(
            profile_ids=("diagnostic",),
            toolchain=Installed(),
            inventory_enabled=False,
        )
        async with Client(create_server(capability_profiles=profiles)) as client:
            catalog = {t.name: t for t in await client.list_tools()}
            assert set(catalog) == {
                "device_status",
                "adb_observe",
                "adb_develop",
                "host_capability_profile",
            }
            reply = await client.call_tool("host_capability_profile", {})
            assert not reply.is_error
            assert isinstance(reply.structured_content, dict)
            Draft202012Validator(catalog["host_capability_profile"].output_schema).validate(
                reply.structured_content
            )
            values = {row["catalog_id"]: row for row in reply.structured_content["capabilities"]}
            assert values["A01"]["state"] == "runnable"
            assert values["A10"]["state"] == "requires_target"
            assert not values["A10"]["authorized"]
            assert values["H01"]["state"] == "not_exposed"
            assert values["E03"]["state"] == "unavailable"
            assert all(row["risk"] in {"D0", "D1"} for row in values.values())

    asyncio.run(check())


def test_inventory_switch_must_be_a_real_boolean() -> None:
    with pytest.raises(ValueError, match="registration flag"):
        cp.CapabilityProfiles(inventory_enabled="true")  # type: ignore[arg-type]


def test_hint_collision_and_malformed_handle_never_issue_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp.secrets, "token_hex", lambda _: "f" * 32)
    hints = cp.TargetHintRegistry()
    reference = hints.issue(_report(), device_id=DEVICE, transport_id=TID)
    assert hints.validate(reference["target_ref"], _report())
    with pytest.raises(ValueError, match="collision"):
        hints.issue(_report(), device_id=DEVICE, transport_id=TID)
    assert hints.validate(None, _report()) is False  # type: ignore[arg-type]

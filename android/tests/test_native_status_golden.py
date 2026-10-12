"""N0.a Native v1 characterization; no attached-device/ADB operations here.

The pure tests check the exact on-device wire oracle and negative mutations.
The same oracle is invoked against the actual Kotlin APK by the separately
preflighted API 30/33/34/36 emulator acceptance scripts.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "android/tests/fixtures/native-status-v1.json"
CORE = ROOT / "scripts/smoke-native-emulator.py"
FGS = ROOT / "scripts/smoke-native-foreground-emulator.py"
MATRIX = ROOT / "scripts/verify_native_api_matrix.py"


def load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load_script("n0a_emulator_core", CORE)
fgs = load_script("n0a_foreground", FGS)
matrix = load_script("n0a_matrix", MATRIX)


def golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def fake_client(
    payload: dict[str, Any],
    *,
    resources: bool = False,
    unknown_accepted: bool = False,
) -> tuple[type, list[str]]:
    calls: list[str] = []

    class Client:
        def __init__(self, _url: str) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def list_tools(self) -> list[Any]:
            return [
                SimpleNamespace(
                    name="device_status",
                    description=(
                        "Local read-only Native MCP availability, no device data or control."
                    ),
                    input_schema={"type": "object", "properties": {}},
                )
            ]

        @property
        def server_capabilities(self) -> Any:
            return SimpleNamespace(
                resources=SimpleNamespace(subscribe=False) if resources else None
            )

        async def call_tool(self, name: str, _args: object, **_kwargs: object) -> Any:
            calls.append(name)
            return SimpleNamespace(
                is_error=(name != "device_status" and not unknown_accepted),
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

    return Client, calls


def run_status(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    **client_kwargs: bool,
) -> list[str]:
    client, calls = fake_client(payload, **client_kwargs)
    monkeypatch.setattr(core, "Client", client)
    asyncio.run(core.assert_status("http://127.0.0.1:38765/mcp"))
    return calls


def test_T_N0A_01_catalog_has_no_hidden_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malicious second published Resource must fail the real HTTP oracle."""
    with pytest.raises(AssertionError, match="[Rr]esource"):
        run_status(monkeypatch, golden(), resources=True)


def test_T_N0A_02_android_v1_exact_fields_no_private_host_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema-valid Host fields are still forbidden in Native's frozen v1."""
    with pytest.raises(AssertionError, match="[Gg]olden|[Cc]ontract|[Dd]rift"):
        run_status(
            monkeypatch,
            {**golden(), "host": {"os": "linux", "architecture": "arm64", "python": "3.13"}},
        )


def test_T_N0A_03_unknown_tool_denied_by_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected successful tools/call must fail the real HTTP oracle."""
    with pytest.raises(AssertionError, match="[Uu]nknown|[Uu]nexpected"):
        run_status(monkeypatch, golden(), unknown_accepted=True)


def test_T_N0A_04_activity_home_stop_matrix_boundaries() -> None:
    """On-device proof must run N2 Activity smoke on all four API targets."""
    for api, serial in (
        (30, "emulator-5560"),
        (33, "emulator-5558"),
        (34, "emulator-5556"),
        (36, "emulator-5554"),
    ):
        commands = matrix.commands_for(api, serial, Path("/tmp/native-contract.apk"))
        assert any(
            Path(argv[1]).name
            in {"smoke-native-legacy-emulator.py", "smoke-native-emulator.py"}
            for argv in commands
        )
    # This is only a harness guard. The four real AVD smokes are mandatory
    # additional evidence for T-N0A-04; this test alone is not proof of Home.


def test_T_N0A_05_foreground_stop_requires_android_and_http_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FGS Stop needs both HTTP closure and actual Android state oracles."""
    events: list[str] = []
    monkeypatch.setattr(fgs, "assert_forward_present", lambda *_: events.append("forward"))
    monkeypatch.setattr(fgs, "await_android_service_and_notification_removed", lambda *_: events.append("android"))
    async def stopped(_url: str) -> None:
        events.append("http")
    monkeypatch.setattr(fgs.core, "await_stopped", stopped)
    fgs.assert_fully_stopped("emulator-5554", 53001, "http://127.0.0.1:53001/mcp")
    assert events == ["forward", "http", "forward", "android"]
    # Actual N3 notification Stop and process-death acceptance is in the AVD suite.


def test_T_N0A_06_mutated_fixture_rejected_without_adb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure negative mutant never invokes ADB or modifies the checked-in fixture."""
    original = GOLDEN.read_bytes()
    mutated = golden()
    mutated["capabilities"]["android.synthetic.secret"] = False
    monkeypatch.setattr(
        core,
        "adb",
        lambda *_args, **_kwargs: pytest.fail("N0.a golden tests must not use ADB"),
    )
    with pytest.raises(AssertionError, match="[Gg]olden|[Cc]ontract|[Dd]rift"):
        run_status(monkeypatch, mutated)
    assert GOLDEN.read_bytes() == original

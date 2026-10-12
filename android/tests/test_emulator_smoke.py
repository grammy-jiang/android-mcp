"""SDK-free, fake-XML negative tests for the emulator-only acceptance tool."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/smoke-native-emulator.py"
spec = importlib.util.spec_from_file_location("emulator_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "serial", ["", "8971a7bf", "device", "-s", "localhost:5555", "emulator-1; reboot"]
)
def test_non_emulator_serial_rejected(serial: str) -> None:
    with pytest.raises(ValueError, match="emulator"):
        module.require_emulator_serial(serial)


@pytest.mark.parametrize("serial", ["emulator-5554", "emulator-5556", "emulator-12345"])
def test_explicit_emulator_serial_accepted(serial: str) -> None:
    module.require_emulator_serial(serial)


@pytest.mark.parametrize("value", ["", "0", "true", "2"])
def test_real_device_rejected_even_if_serial_looks_like_emulator(value: str) -> None:
    with pytest.raises(ValueError, match="kernel"):
        module.require_virtual_target(value)


def test_verified_kernel_emulator() -> None:
    module.require_virtual_target("1\n")


def test_ui_button_center() -> None:
    xml = (
        '<hierarchy><node text="Other" bounds="[1,2][3,4]"/>'
        '<node text="Start local read-only MCP" bounds="[10,20][110,60]"/></hierarchy>'
    )
    assert module.get_button_center(xml) == (60, 40)


@pytest.mark.parametrize(
    "xml",
    [
        "<hierarchy/>",
        '<hierarchy><node text="Start local read-only MCP" bounds="[1,2][1,4]"/></hierarchy>',
        '<hierarchy><node text="Start local read-only MCP" bounds="unsafe"/></hierarchy>',
        (
            '<hierarchy><node text="Start local read-only MCP" bounds="[1,2][5,6]"/>'
            '<node text="Start local read-only MCP" bounds="[1,2][5,6]"/></hierarchy>'
        ),
    ],
)
def test_button_ambiguity_or_invalid_bounds_fail_closed(xml: str) -> None:
    with pytest.raises(ValueError):
        module.get_button_center(xml)

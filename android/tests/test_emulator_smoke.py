"""SDK-free, fake-XML negative tests for the emulator-only acceptance tool."""

from __future__ import annotations

import asyncio
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


def test_android_all_caps_rendering_does_not_hide_start_button() -> None:
    xml = (
        '<hierarchy><node text="START LOCAL READ-ONLY MCP" '
        'class="android.widget.Button" bounds="[10,20][110,60]"/></hierarchy>'
    )
    assert module.get_button_center(xml) == (60, 40)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:38765/mcp",
        "https://127.0.0.1:38765/mcp",
        "http://127.0.0.1:38765/other",
        "http://127.0.0.1/mcp",
    ],
)
def test_shutdown_probe_denies_non_exact_local_endpoint(url: str) -> None:
    with pytest.raises(ValueError, match="localhost"):
        asyncio.run(module.http_server_responds(url))


def test_shutdown_probe_distinguishes_real_http_response_from_disconnected_socket() -> (
    None
):
    async def exercise() -> None:
        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await reader.read(500)
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/mcp"
        assert await module.http_server_responds(url)
        server.close()
        await server.wait_closed()
        assert not await module.http_server_responds(url)

    asyncio.run(exercise())


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

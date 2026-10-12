"""Fail-closed live smoke input tests: never start HTTP or require hardware."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/smoke_host_live.py"


def _call(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_live_smoke_requires_explicit_serial():
    result = _call()
    assert result.returncode == 2
    assert "--device-id" in result.stderr


def test_live_smoke_rejects_invalid_device_before_running():
    result = _call("--device-id", "bad serial with spaces")
    assert result.returncode == 2
    assert "Invalid device serial" in result.stderr


def test_live_smoke_rejects_excessive_logcat_lines():
    result = _call("--device-id", "TABLET", "--logcat-lines", "2001")
    assert result.returncode == 2
    assert "Logcat line count" in result.stderr


def test_live_smoke_rejects_duplicate_probes():
    result = _call("--device-id", "TABLET", "--probes", "battery", "battery")
    assert result.returncode == 2
    assert "different probe groups" in result.stderr


def test_live_smoke_retries_fastmcp_runtime_error_before_server_ready(monkeypatch):
    import asyncio
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("smoke_host_live", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    attempts = []

    class FlakyClient:
        async def __aenter__(self):
            attempts.append("connect")
            if len(attempts) == 1:
                raise RuntimeError("Client failed to connect: All connection attempts failed")
            return self

        async def __aexit__(self, *_):
            return False

        async def list_tools(self):
            return [SimpleNamespace(name="device_status")]

    async def immediate_sleep(_):
        return None

    monkeypatch.setattr(module, "Client", lambda _: FlakyClient())
    monkeypatch.setattr(module.asyncio, "sleep", immediate_sleep)
    assert asyncio.run(module._catalog_when_ready("http://127.0.0.1:1/mcp/")) == ["device_status"]
    assert len(attempts) == 2


def test_live_smoke_reads_wire_structured_content_not_sdk_parsed_data():
    """FastMCP .data becomes a dynamic model when outputSchema is explicit."""
    import importlib.util
    from types import SimpleNamespace

    import pytest

    spec = importlib.util.spec_from_file_location("smoke_host_live_data", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    expected = {"schema_version": 1, "runtime": "host"}
    typed_data = SimpleNamespace(schema_version=1, runtime="host")
    success = SimpleNamespace(is_error=False, data=typed_data, structured_content=expected)
    assert module._body(success) == expected

    with pytest.raises(RuntimeError, match="Malformed or failed MCP tool result"):
        module._body(SimpleNamespace(is_error=True, structured_content=expected))
    with pytest.raises(RuntimeError, match="Malformed or failed MCP tool result"):
        module._body(SimpleNamespace(is_error=False, structured_content=None))

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

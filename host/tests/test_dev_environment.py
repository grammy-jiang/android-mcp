"""Developer doctor must work without Android SDK or a connected device."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev.py"


def test_read_only_development_doctor_reports_json():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "doctor", "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    status = json.loads(completed.stdout)
    assert status["status"] == "ok"
    assert status["lock_consistent"] is True
    assert status["git_root_valid"] is True
    assert status["git"] and status["uv"]
    assert isinstance(status["adb_optional"], bool)
    assert isinstance(status["hooks_installed"]["pre-commit"], bool)
    assert isinstance(status["hooks_installed"]["pre-push"], bool)

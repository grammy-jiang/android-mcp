"""Validate all result states against the cross-runtime JSON Schema contract."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.command_runner import RunResult
from android_mcp_host.operations import OperationService

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/adb-development.v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


class Online:
    def inspect(self):
        return AdbReport(True, "/mock/adb", "v1", None, (Device("DEV123", "device", {}),))


def test_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_ok_dry_run_denial_and_partial_responses_conform(tmp_path):
    apk = tmp_path / "demo.apk"
    apk.write_bytes(b"PK\x03\x04test")
    for raw in [
        {"type": "logcat_snapshot"},
        {"type": "shell", "command": "whoami"},
        {"type": "install_apk", "apk_path": str(apk)},
        {"type": "package_details", "package": "com.example.test"},
    ]:
        for dry_run in (False, True):
            svc = OperationService(
                Online(),
                allowed_apk_roots=(tmp_path,),
                runner=lambda *args: RunResult(0, "data", "", False),
            )
            response = svc.execute("DEV123", raw, dry_run=dry_run)
            VALIDATOR.validate(response)


def test_failure_timeout_and_capture_limit_conform():
    for output in (
        RunResult(1, "", "", False),
        RunResult(0, "X" * 100000, "", True),
    ):
        svc = OperationService(Online(), runner=lambda *args, value=output: value)
        VALIDATOR.validate(svc.execute("DEV123", {"type": "logcat_snapshot"}))


def test_input_schema_matches_safe_typed_operations():
    action_schema = json.loads(
        (ROOT / "contracts/adb-development-action.v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(action_schema)
    validator = Draft202012Validator(action_schema)
    valid = (
        {"type": "logcat_snapshot", "lines": 25},
        {"type": "logcat_snapshot"},
        {"type": "package_details", "package": "com.example.app"},
        {
            "type": "instrument_test",
            "package": "com.example.tests",
            "runner": "androidx.test.runner.AndroidJUnitRunner",
        },
        {"type": "install_apk", "apk_path": "/tmp/review.apk", "allow_test": True},
    )
    for action in valid:
        assert validator.is_valid(action), action
    invalid = (
        {"type": "root"},
        {"type": "logcat_snapshot", "lines": True},
        {"type": "logcat_snapshot", "lines": -1},
        {"type": "package_details", "package": "com.app; id"},
        {"type": "package_details", "package": "a"},
        {"type": "instrument_test", "package": "com.app", "runner": "runner; reboot"},
        {"type": "install_apk", "apk_path": "/tmp/x.apk", "arbitrary_shell": "id"},
    )
    for action in invalid:
        assert not validator.is_valid(action), action

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbClient
from android_mcp_host.status import build_status

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "device-status.v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def test_schema_itself_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_example_fixtures_validate():
    for name in ("host-no-device.json", "native-example.json"):
        data = json.loads((CONTRACTS / "fixtures" / name).read_text(encoding="utf-8"))
        VALIDATOR.validate(data)


def test_runtime_missing_adb_matches_shared_contract():
    status = build_status(
        AdbClient(locator=lambda _: None),
        system="Darwin",
        architecture="arm64",
        python_version="3.14.8",
    )
    VALIDATOR.validate(status)
    assert status["runtime"] == "host"
    assert status["devices"] == []
    assert status["capabilities"]["adb.discovery"] is False


def test_linux_platform_is_normalized_and_valid():
    status = build_status(
        AdbClient(locator=lambda _: None),
        system="Linux",
        architecture="aarch64",
        python_version="3.13.5",
    )
    VALIDATOR.validate(status)
    assert status["host"]["os"] == "linux"

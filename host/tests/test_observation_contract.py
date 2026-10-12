"""Shared JSON schema acceptance for the M1 observation envelope."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.probes import PROBES, ProbeService

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "adb-observation.v1.schema.json"


def test_schema_is_valid():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_device_observation_validates_both_success_and_error():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    class Discovery:
        def inspect(self):
            return AdbReport(True, "/mock/adb", "37", None, (Device("SERIAL", "device", {}),))

    import subprocess

    service = ProbeService(
        Discovery(),
        adb_executable="/mock/adb",
        reader=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "Enforcing\n", ""),
    )
    validator.validate(service.observe("SERIAL", ["selinux"]))
    validator.validate(service.observe("SERIAL", ["invalid"]))
    validator.validate(service.observe("NO_DEVICE", ["battery"]))


def test_schema_enumerates_every_registered_probe_and_accepts_outputs():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    names = set(schema["properties"]["results"]["items"]["properties"]["probe"]["enum"])
    assert names == set(PROBES)

    class Discovery:
        def inspect(self):
            return AdbReport(True, "/mock/adb", "37", None, (Device("SERIAL", "device", {}),))

    import subprocess

    service = ProbeService(
        Discovery(),
        adb_executable="/mock/adb",
        reader=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "a\\nb\\n", ""),
    )
    validator = Draft202012Validator(schema)
    for name in PROBES:
        result = service.observe("SERIAL", [name])
        assert result["status"] == "ok"
        validator.validate(result)

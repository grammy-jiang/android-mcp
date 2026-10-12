#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# Build both distribution formats and install the wheel in a truly clean venv.
uv build --project "$repo_root/host" --out-dir "$tmpdir/dist"
[[ "$(find "$tmpdir/dist" -type f -name '*.whl' | wc -l | tr -d ' ')" == 1 ]]
[[ "$(find "$tmpdir/dist" -type f -name '*.tar.gz' | wc -l | tr -d ' ')" == 1 ]]
wheel="$(find "$tmpdir/dist" -type f -name '*.whl' -print -quit)"
py="$(printenv HOST_PYTHON || echo 3.13)"
uv python install "$py"
uv venv --python "$py" "$tmpdir/clean-venv"
uv pip install --python "$tmpdir/clean-venv/bin/python" "$wheel"
"$tmpdir/clean-venv/bin/android-mcp-host" doctor > "$tmpdir/doctor.json"
"$tmpdir/clean-venv/bin/python" - "$tmpdir/doctor.json" <<'PY'
import json
import sys

from android_mcp_host.server import create_server
from android_mcp_host.toolchain_inventory import (
    ToolchainInventory,
    get_toolchain_output_schema,
)
from android_mcp_host.capability_profiles import (
    CapabilityProfiles,
    get_capability_output_schema,
    load_ledger,
)
from android_mcp_host.adb import AdbClient
from android_mcp_host.device_discovery import DeviceDiscovery, get_device_list_output_schema

with open(sys.argv[1], encoding="utf-8") as report_file:
    report = json.load(report_file)
assert report["schema_version"] == 1
assert report["runtime"] == "host"
assert "devices" in report
assert callable(create_server)
assert get_toolchain_output_schema()["$id"] == "urn:android-mcp:host-toolchain-inventory:v1"
assert create_server(toolchain_inventory=ToolchainInventory(paths={})) is not None
assert get_capability_output_schema()["$id"] == "urn:android-mcp:host-capability-profile:v1"
assert len(load_ledger()) == 95
assert CapabilityProfiles().snapshot()["mutation_enabled"] is False
assert create_server(capability_profiles=CapabilityProfiles()) is not None
assert get_device_list_output_schema()["$id"] == "urn:android-mcp:adb-device-list:v1"
assert DeviceDiscovery(AdbClient(locator=lambda _: None)).list_devices()["status"] == "unavailable"
assert create_server(adb_discovery=DeviceDiscovery(AdbClient(locator=lambda _: None))) is not None
PY
echo "Host sdist/wheel clean-install and CLI doctor passed."

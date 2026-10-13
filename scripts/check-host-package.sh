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
from android_mcp_host.durable_jobs import DurableJobStore, get_job_status_schema
from android_mcp_host.private_artifact_store import (
    PrivateArtifactStore,
    get_artifact_metadata_schema,
)
from android_mcp_host.android_build_preflight import AndroidBuildPreflight, get_build_preflight_output_schema
from pathlib import Path
from android_mcp_host.sdk_ndk_inventory import SdkNdkInventory, get_sdk_ndk_output_schema
from android_mcp_host.fastboot_inventory import FastbootInventory, get_fastboot_output_schema
from android_mcp_host.logcat_filters import LogcatFilters, get_logcat_output_schema
from android_mcp_host.package_inspector import PackageInspector, get_package_output_schema
from android_mcp_host.system_snapshot import SystemSnapshot, get_snapshot_output_schema
from android_mcp_host.adb_transport import get_transport_output_schema, AdbTransport
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
assert get_job_status_schema()["$id"] == "urn:android-mcp:host-durable-job-status:v1"
from tempfile import TemporaryDirectory
with TemporaryDirectory() as job_tmp:
    private_jobs = DurableJobStore(Path(job_tmp).resolve(strict=True) / "private-jobs")
    assert create_server(durable_jobs=private_jobs, job_owner="package-fixture") is not None
assert get_artifact_metadata_schema()["$id"] == "urn:android-mcp:host-private-artifact-metadata:v1"
from tempfile import TemporaryDirectory
with TemporaryDirectory() as private_tmp:
    private_store = PrivateArtifactStore(Path(private_tmp).resolve(strict=True) / "objects-private")
    private_record = private_store.put("packaging-test", b"synthetic", mime_type="application/octet-stream")
    assert private_store.public_metadata("packaging-test", private_record["handle"])["status"] == "ok"
    assert create_server(artifact_store=private_store, artifact_owner="packaging-test") is not None
assert get_build_preflight_output_schema()["$id"] == "urn:android-mcp:host-android-build-preflight:v1"
assert create_server(build_preflight=AndroidBuildPreflight(Path.home() / "Projects" / "missing")) is not None
assert get_sdk_ndk_output_schema()["$id"] == "urn:android-mcp:host-sdk-ndk-inventory:v1"
assert create_server(sdk_ndk_inventory=SdkNdkInventory(fixed_binaries={})) is not None
assert get_fastboot_output_schema()["$id"] == "urn:android-mcp:host-fastboot-inventory:v1"
assert create_server(fastboot_inventory=FastbootInventory(executable=None)) is not None
assert get_logcat_output_schema()["$id"] == "urn:android-mcp:host-logcat-filters:v1"
assert create_server(logcat_filter=LogcatFilters()) is not None
assert get_package_output_schema()["$id"] == "urn:android-mcp:host-package-diagnostics:v1"
assert create_server(package_inspector=PackageInspector()) is not None
assert get_snapshot_output_schema()["$id"] == "urn:android-mcp:host-system-snapshot:v1"
assert create_server(system_snapshot=SystemSnapshot()) is not None
assert get_transport_output_schema()["$id"] == "urn:android-mcp:adb-transport-inspection:v1"
assert create_server(adb_transport=AdbTransport()) is not None
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

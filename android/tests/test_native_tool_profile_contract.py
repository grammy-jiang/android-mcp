"""N1.d strict native/host public MCP compatibility and inert profiles.

No Android hardware or live services are accessed by these policy checks.
Actual Kotlin SDK public list/call is exercised by the existing loopback
and preverified disposable emulator acceptance runners.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
STATUS = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeLocalStatus.kt"
PROFILES = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeToolProfiles.kt"
HOST = ROOT / "host/src/android_mcp_host/server.py"
HOST_ACCEPTANCE = ROOT / "host/tests/test_host_http_fake_adb.py"


def test_public_native_registry_is_exactly_one_approved_status_tool() -> None:
    source = NATIVE.read_text()
    assert source.count("server.addTool(") == 1
    assert 'name = "device_status"' in source
    assert "NativeToolProfiles" not in source
    for forbidden in (
        "native_build_snapshot",
        "native_system_snapshot",
        "native_app_health",
        "native_screen_capture",
        "native_accessibility",
        "native_package_inventory",
        "native_tap",
    ):
        assert forbidden not in source


def test_fake_capability_catalog_cannot_be_installed_over_live_mcp() -> None:
    profiles = PROFILES.read_text()
    assert "fun liveTools(" in profiles
    assert "fun syntheticTools(" in profiles
    assert "fun publicTools()" in profiles
    assert "fun liveTools(approvedByModel: Boolean): List<NativeToolDescriptor> = publicTools()" in profiles
    assert "permit?.processEpoch != epoch" in profiles
    assert "testSignature" in profiles
    assert "context.packagePermissions" in profiles
    assert "FOCUSED_NAMES" in profiles
    assert "NativeLocalCallerGuard" not in NATIVE.read_text().split("private fun statusServer()")[1]


def test_shared_status_v1_fields_and_host_default_registry_untouched() -> None:
    status = STATUS.read_text()
    assert 'put("schema_version", 1)' in status
    assert 'put("runtime", "android")' in status
    assert 'put("android.native.loopback_status", true)' in status
    assert 'put("android.accessibility.observe", false)' in status
    assert 'put("android.privileged", false)' in status
    host_acceptance = HOST_ACCEPTANCE.read_text()
    assert '["device_status", "adb_observe", "adb_develop"]' in host_acceptance
    host = HOST.read_text()
    for name in ("device_status", "adb_observe", "adb_develop"):
        assert f'def {name}(' in host or f'async def {name}(' in host


def test_synthetic_schema_error_codes_are_bounded_and_read_only() -> None:
    profiles = PROFILES.read_text()
    assert '"additionalProperties", false' in profiles
    assert '"synthetic_only", true' in profiles
    assert '"schema_version", 1' in profiles
    assert "readOnly = true" in profiles
    assert "PreviewStatus.DENIED" in profiles
    assert "PreviewStatus.entries" in profiles
    assert "openWorldHint" not in profiles  # actual SDK metadata is test-only

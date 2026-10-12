"""N1.a source/provenance negative tests. No Android device is accessed."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidBuildSnapshotReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
SOURCE = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeBuildSnapshot.kt"


def test_n1a_reads_only_coarse_safe_android_build_fields() -> None:
    source = ADAPTER.read_text()
    assert "Build.VERSION.SDK_INT" in source
    assert "Build.VERSION.RELEASE" in source
    assert "Build.MANUFACTURER" in source
    assert "Build.MODEL" in source
    assert "Build.SUPPORTED_ABIS.toList()" in source
    assert "getPackageInfo(context.packageName, 0)" in source
    for forbidden in (
        "Build.getSerial",
        "Build.SERIAL",
        "Build.FINGERPRINT",
        "Settings.Secure",
        "AdvertisingId",
        "TelephonyManager",
        "WifiInfo",
        "NetworkInterface",
        "ANDROID_ID",
        "IMEI",
    ):
        assert forbidden not in source
    assert "NativeBuildSnapshots.normalize" in source
    assert "catch (_: RuntimeException)" in source


def test_n1a_remains_internal_until_caller_auth_review() -> None:
    gateway = GATEWAY.read_text()
    adapter = ADAPTER.read_text()
    assert "internal object AndroidBuildSnapshotReader" in adapter
    assert "NativeBuildSnapshot" not in gateway
    assert "AndroidBuildSnapshotReader" not in gateway
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway


def test_n1a_bounds_and_redaction_are_enforced_by_kotlin_normalizer() -> None:
    code = SOURCE.read_text()
    assert "MAX_FIELD_CHARS = 96" in code
    assert "MAX_ABIS = 8" in code
    assert '"serial"' in code
    assert '"android_id"' in code
    assert '"advertising_id"' in code
    assert '"fingerprint"' in code
    assert "JsonNull" in code
    assert "NativeBuildAvailability.PARTIAL" in code
    assert "NativeBuildAvailability.UNSUPPORTED" in code

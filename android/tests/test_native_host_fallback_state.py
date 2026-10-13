"""N5.d private Host/Native fallback: provenance, no untrusted ADB failover."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeHostFallback.kt"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidHostFallbackBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n5d_01_host_only_has_separate_adb_provenance_and_read_only_suggestion() -> None:
    code = MODEL.read_text()
    assert "HOST_ADB" in code
    assert "NATIVE_LOOPBACK" in code
    assert "FallbackDecision.HOST_READ_ONLY" in code
    assert "FallbackDecision.NATIVE_READ_ONLY" in code
    assert "SUGGEST_READ_ONLY" in code
    assert "HOST_ADB_OBSERVE" in code
    assert "NATIVE_STATUS" in code


def test_t_n5d_02_unknown_and_both_providers_never_autoselect() -> None:
    code = MODEL.read_text()
    assert "FallbackDecision.BOTH_AVAILABLE" in code
    assert "FallbackDecision.UNKNOWN" in code
    assert "FallbackDecision.UNAVAILABLE" in code
    assert 'put("automatic_failover", false)' in code
    assert 'put("read_only", true)' in code
    assert 'put("write_capability_enabled", false)' in code
    assert 'put("synthetic_only", true)' in code


def test_t_n5d_03_boot_serial_pairing_and_freshness_are_checked() -> None:
    code = MODEL.read_text()
    assert "host.hostKey != binding.expectedHostKey" in code
    assert "host.serial != binding.expectedSerial" in code
    assert "host.bootEpoch != binding.expectedHostBootEpoch" in code
    assert "native.installationId != binding.expectedNativeInstallationId" in code
    assert "native.bootEpoch != binding.expectedNativeBootEpoch" in code
    assert "!host.signedIdentityVerified" in code
    assert "!host.transportVerified" in code
    assert "MAX_PROBE_AGE_MS = 5_000L" in code
    assert "binding.expiryElapsedMs < nowElapsedMs" in code


def test_t_n5d_04_write_lease_never_authorizes_sensitive_fallback() -> None:
    code = MODEL.read_text()
    assert "writeLeaseActive: Boolean = false" in code
    for forbidden in ("INSTALL_APK", "ROOT", "UI_WRITE", "ACCESSIBILITY", "REBOOT"):
        assert forbidden in code
    assert "FallbackCall.DENIED" in code
    assert "FallbackCall.UNSUPPORTED" in code
    assert "FallbackCall.UNAVAILABLE" in code
    assert "FallbackCall.SUGGEST_READ_ONLY" in code
    for dangerous in ("Runtime.getRuntime(", "ProcessBuilder(", "exec(", "startActivity("):
        assert dangerous not in code


def test_t_n5d_05_production_android_adapter_refuses_even_fake_pairing() -> None:
    code = ADAPTER.read_text()
    assert "internal object AndroidHostFallbackBoundary" in code
    assert "FallbackDecision.DENIED" in code
    assert "providers = emptyList()" in code
    for dangerous in (
        "adb ", "getRunningAppProcesses(",
        "UsbManager", "startService(", "startActivity(",
        "Runtime.getRuntime(", "ProcessBuilder(", "Socket(",
    ):
        assert dangerous not in code
    live = GATEWAY.read_text()
    assert live.count("server.addTool(") == 1
    assert 'name = "device_status"' in live
    assert "AndroidHostFallbackBoundary" not in live


def test_t_n5d_06_no_physical_android_or_extra_permission_requested() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {
        entry.get(ANDROID + "name") for entry in manifest.findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    app = manifest.find("application")
    assert app is not None and app.findall("provider") == []
    assert manifest.findall("queries") == []

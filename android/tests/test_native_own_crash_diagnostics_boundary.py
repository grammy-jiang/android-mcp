"""N5.a app-only crash diagnostics and deny-by-default Android access."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidOwnCrashBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
CORE = (
    ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle"
    / "NativeOwnCrashDiagnostics.kt"
)
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n5a_01_private_bounded_versioned_diagnostics_and_retention() -> None:
    source = CORE.read_text()
    for required in (
        "MAX_REPORT_BYTES = 16 * 1024",
        "RETENTION_MS = 120_000L",
        "MAX_RECORDS = 4",
        r'\"schema_version\"',
        "input.uptimeMs",
        "input.code.name.lowercase()",
        'privateOwner.create(bytes, "application/json")',
        "NativeArtifactStore(",
        "privateOwner.purgeExpired()",
    ):
        assert required in source


def test_t_n5a_02_no_global_logcat_or_foreign_process_reader() -> None:
    source = CORE.read_text() + ADAPTER.read_text()
    assert 'input.packageName != OWN_PACKAGE' in source
    assert '"org.androidmcp.nativeapp"' in source
    for forbidden in (
        "logcat -d",
        "Runtime.getRuntime(",
        "ProcessBuilder(",
        "getRunningAppProcesses(",
        "getHistoricalProcessExitReasons(",
        "getSystemService(ActivityManager",
        "FileInputStream(",
        "getExternalStorageDirectory(",
        "ApplicationExitInfo",
        "getStackTrace(",
        "Thread.getAllStackTraces(",
    ):
        assert forbidden not in source


def test_t_n5a_03_secrets_are_never_serialized_or_in_diagnostics_string() -> None:
    source = CORE.read_text()
    assert 'NativeCrashInput([REDACTED])' in source
    assert 'artifact=[REDACTED]' in source
    assert '"privateExceptionMessage"' not in source
    assert '"stacktrace"' not in source
    assert "VERSION_FORBIDDEN" in source
    assert "bytes.fill(0)" in source
    assert r'\"read_only\"' in source
    assert r'\"synthetic_only\"' in source


def test_t_n5a_04_unconfirmed_crash_commit_and_restart_do_not_claim_success() -> None:
    code = CORE.read_text()
    assert "NativeCrashState.INCOMPLETE" in code
    assert "faulted = true" in code
    assert "store?.close()" in code
    assert "closed = true" in code
    assert "purgeExpired()" in code


def test_t_n5a_05_invalid_owner_epoch_cannot_discover_prior_report() -> None:
    source = CORE.read_text()
    assert "val processEpoch = UUID.randomUUID().toString()" in source
    assert "input.processEpoch != processEpoch" in source
    assert "HANDLE.matches(handle)" in source
    assert "store?.read(handle)" in source
    assert "store?.activeCount()" in source
    assert "nonces.clear()" in source


def test_t_n5a_06_public_mcp_and_manifest_cannot_expose_own_crash_report() -> None:
    adapter = ADAPTER.read_text()
    assert "internal object AndroidOwnCrashBoundary" in adapter
    assert "NativeCrashState.DENIED" in adapter
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidOwnCrashBoundary" not in gateway
    assert "NativeOwnCrashDiagnostics" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    declared = {
        item.get(ANDROID + "name")
        for item in manifest.findall("uses-permission")
    }
    assert declared == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall("queries") == []
    assert manifest.find("application") is not None

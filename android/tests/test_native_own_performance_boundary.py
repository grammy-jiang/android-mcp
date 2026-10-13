"""N5.b one-shot own-app CPU/memory/latency policy: no global profiler."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidOwnPerformanceReader.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeOwnPerformance.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n5b_01_own_process_stable_time_units_and_heap_measurements() -> None:
    source = ADAPTER.read_text()
    assert "NativeOwnPerformanceSession()" in source
    assert "Process.getElapsedCpuTime()" in source
    assert "Runtime.getRuntime()" in source
    assert "Debug.getNativeHeapAllocatedSize()" in source
    assert "SystemClock.elapsedRealtime()" in source
    assert "eventLatencyMs = null" in source
    assert 'context.packageName == "org.androidmcp.nativeapp"' in source


def test_t_n5b_02_no_systemwide_perfetto_root_or_process_enumeration() -> None:
    source = ADAPTER.read_text()
    for denied in (
        "getRunningAppProcesses(",
        "getMemoryInfo(",
        "Debug.MemoryInfo(",
        "Process.killProcess(",
        "getHistoricalProcessExitReasons(",
        "getSystemService(ActivityManager",
        "Perfetto",
        "Trace.beginSection(",
        "Trace.endSection(",
        "ProcessBuilder(",
        "Runtime.getRuntime().exec(",
        "android.util.Log",
        "Log.",
        "registerListener(",
        "startService(",
    ):
        assert denied not in source
    model = MODEL.read_text()
    assert "fun globalProfilerAllowed(): Boolean = false" in model
    assert "fun liveBackgroundSamplingAllowed(): Boolean = false" in model
    assert "if (input.epoch != epoch || input.requestGlobalProfile)" in model


def test_t_n5b_03_invalid_oem_values_and_unsupported_versions_denied() -> None:
    model = MODEL.read_text()
    assert "input.apiLevel !in 30..100" in model
    assert "input.ownProcessCpuMs?.takeIf" in model
    assert "input.ownJavaHeapUsedBytes?.takeIf" in model
    assert "input.ownNativeHeapUsedBytes?.takeIf" in model
    assert "input.eventLatencyMs?.takeIf" in model
    assert "OwnPerformanceStatus.PARTIAL" in model
    assert "OwnPerformanceStatus.UNSUPPORTED" in model


def test_t_n5b_04_lifecycle_and_rate_limits_prohibit_surveillance_stream() -> None:
    model = MODEL.read_text()
    assert "OwnPerformanceStop" in model
    assert "FGS_STOP" in model
    assert "PROCESS_DEATH" in model
    assert "CLIENT_DISCONNECT" in model
    assert "MAX_SAMPLES = 16" in model
    assert "MIN_SAMPLE_INTERVAL_MS = 1_000L" in model
    assert "observedAt.clear()" in model
    assert "stopped = true" in model
    assert "input.requestHighRateStream" in model
    assert "OwnPerformanceStatus.THROTTLED" in model


def test_t_n5b_05_public_status_and_manifest_unchanged() -> None:
    live = GATEWAY.read_text()
    assert live.count("server.addTool(") == 1
    assert 'name = "device_status"' in live
    assert "AndroidOwnPerformanceReader" not in live
    assert "native_performance" not in live
    manifest = ET.parse(MANIFEST).getroot()
    names = {e.get(ANDROID + "name") for e in manifest.findall("uses-permission")}
    assert names == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall("queries") == []


def test_t_n5b_06_no_pid_private_trace_or_foreign_package_in_model_json() -> None:
    source = MODEL.read_text()
    assert 'put("own_cpu_time_ms"' in source
    assert 'put("own_java_heap_bytes"' in source
    assert 'put("own_native_heap_bytes"' in source
    assert 'put("own_event_latency_ms"' in source
    assert 'put("real_background_collection", false)' in source
    assert "private_path" not in source
    assert "stacktrace" not in source
    assert "ownerPid" not in source

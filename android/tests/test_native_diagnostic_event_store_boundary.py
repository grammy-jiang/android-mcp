"""N5.c durable but unexposed app-own diagnostic event ledger safety."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
STORE = (
    ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle"
    / "NativeDiagnosticEventStore.kt"
)
ADAPTER = APP / "AndroidEventStoreBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n5c_01_bounded_origin_sensitivity_id_and_monotonic_timestamp() -> None:
    source = STORE.read_text()
    for marker in (
        "enum class OwnEventOrigin",
        "FOREGROUND_SERVICE",
        "enum class OwnEventSensitivity",
        "REDACTED_PRIVATE",
        "val id: Long",
        "val elapsedMs: Long",
        "nextId++",
        "timestamp <= lastElapsed",
        "input" if False else "OwnDiagnosticEvent(",
    ):
        assert marker in source
    assert "MAX_EVENTS = 64" in source
    assert "MAX_PAGE = 8" in source
    assert "MAX_NONCES = 128" in source


def test_t_n5c_02_subscriber_cursor_ack_and_duplicate_nonce_are_bound() -> None:
    source = STORE.read_text()
    assert "if (digest in seenNonces)" in source
    assert "OwnEventState.DUPLICATE" in source
    assert "token != subscriberToken" in source
    assert "cursor != lastCursor" in source
    assert "throughId > issuedThrough" in source
    assert "OwnEventAckState.ALREADY_ACKED" in source
    assert "throughId <= ackedThrough" in source
    assert "limit.coerceIn(1, MAX_PAGE)" in source
    assert "FAKE_OWNER_NAMES" in source


def test_t_n5c_03_recovery_reconciles_unknown_delivery_not_false_ack() -> None:
    source = STORE.read_text()
    assert "recoveredUnacked = records.isNotEmpty()" in source
    assert "OwnEventPageState.UNCERTAIN" in source
    assert "fun simulateProcessDeath()" in source
    assert "fun acknowledge(" in source
    assert "OwnEventAckState.ACKNOWLEDGED" in source
    assert "FileChannel.open(" in source
    assert "OverlappingFileLockException" in source
    assert "StandardCopyOption.ATOMIC_MOVE" in source
    assert "outputChannel.force(true)" in source
    assert "LinkOption.NOFOLLOW_LINKS" in source


def test_t_n5c_04_backpressure_expiration_privacy_and_storage_limits() -> None:
    source = STORE.read_text()
    assert "RETENTION_MS = 120_000L" in source
    assert "MAX_JOURNAL_BYTES = 32 * 1024" in source
    assert "records.removeFirst()" in source
    assert "droppedOverflow++" in source
    assert "droppedExpired++" in source
    assert "sha256(nonce)" in source
    assert "seenNonces.addLast(digest)" in source
    assert "FILE_PERMISSIONS = PosixFilePermissions.fromString" in source
    assert 'PosixFilePermissions.fromString("rw-------")' in source
    assert 'PosixFilePermissions.fromString("rwx------")' in source
    assert '"subscriber_delivery_confirmed"' not in source  # escaped in Kotlin output
    assert "subscriber_delivery_confirmed" in source


def test_t_n5c_05_invalid_root_cursor_owner_denies_public_mcp() -> None:
    source = STORE.read_text()
    assert "Files.isSymbolicLink(privateRoot)" in source
    assert "Files.isSymbolicLink(dir)" in source
    assert "Files.isSymbolicLink(ownerFile)" in source
    assert "OwnEventPageState.DENIED" in source
    assert "caller !in FAKE_OWNER_NAMES" in source
    assert "if (stopped)" in source
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativeDiagnosticEventStore" not in gateway
    assert "AndroidEventStoreBoundary" not in gateway


def test_t_n5c_06_stop_unsubscribe_erases_journal_no_privileged_permissions() -> None:
    source = STORE.read_text()
    assert "Files.deleteIfExists(journal)" in source
    assert "purgeStaleStaging()" in source
    assert "try { lock.release() }" in source
    assert "try { channel.close() }" in source
    assert "subscriberToken = null" in source
    assert "seenNonces.clear()" in source
    adapter = ADAPTER.read_text()
    assert "OwnEventPage(OwnEventPageState.DENIED)" in adapter
    for forbidden in (
        "startActivity(",
        "startService(",
        "registerReceiver(",
        "Logcat",
        "getRunningAppProcesses",
        "getHistoricalProcessExitReasons(",
        "requestPermissions(",
    ):
        assert forbidden not in adapter
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {node.get(ANDROID + "name") for node in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    app = manifest.find("application")
    assert app is not None
    assert app.findall("provider") == []

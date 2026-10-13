"""N4.c SDK-free SAF URI permission and Activity-result security invariants."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidSafPickerProbe.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeSafGrantPolicy.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n4c_01_os_scoped_grant_and_own_picker_result_not_model_claim() -> None:
    source = ADAPTER.read_text()
    for marker in (
        "internal object AndroidSafPickerProbe",
        "ownPickerSessionVerified",
        "resultCode == Activity.RESULT_OK",
        "context.checkUriPermission(",
        "Process.myPid()",
        "Process.myUid()",
        "PackageManager.PERMISSION_GRANTED",
        "Intent.FLAG_GRANT_READ_URI_PERMISSION",
        "Intent.FLAG_GRANT_WRITE_URI_PERMISSION",
        "context.contentResolver.persistedUriPermissions",
        "NativeSafGrantPolicy" if False else "SyntheticSafPickerResult",
    ):
        assert marker in source


def test_t_n4c_02_no_arbitrary_uri_parser_or_external_sdcard_paths() -> None:
    source = MODEL.read_text()
    for marker in (
        'uri.scheme != "content"',
        "uri.rawUserInfo != null",
        "uri.rawQuery != null",
        "uri.rawFragment != null",
        "authority !in authorities",
        "path.contains",
        "GRANT_TTL_MS",
        "MAX_ACTIVE = 8",
        "MAX_NONCES = 256",
        "SafGrantStatus.STALE",
        "SafGrantStatus.REPLAY_DENIED",
        "fun realDocumentIoAllowed(): Boolean = false",
    ):
        assert marker in source
    for forbidden in (
        "FileInputStream(",
        "FileOutputStream(",
        "openInputStream(",
        "openOutputStream(",
        "takePersistableUriPermission(",
        "getExternalStorageDirectory(",
        "Environment.getExternal",
        "Runtime.getRuntime(",
        "ProcessBuilder(",
    ):
        assert forbidden not in source


def test_t_n4c_03_read_write_and_persistence_not_implicitly_granted() -> None:
    source = MODEL.read_text()
    assert "FLAG_READ = 1" in source
    assert "FLAG_WRITE = 2" in source
    assert "FLAG_PERSISTABLE = 64" in source
    assert "flags and FLAG_READ != 0 && result.osReadGranted == true" in source
    assert "flags and FLAG_WRITE != 0 && result.osWriteGranted == true" in source
    assert "result.osPersistedRead == true" in source
    assert "result.osPersistedWrite == true" in source
    assert "fun revoke(handle: String)" in source
    assert "real_io_allowed" in source


def test_t_n4c_05_manifest_no_manage_external_storage_or_broad_file_grant() -> None:
    manifest = ET.parse(MANIFEST).getroot()
    actual = {
        p.get(ANDROID + "name") for p in manifest.findall("uses-permission")
    }
    assert actual == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    for forbidden in (
        "android.permission.MANAGE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.MANAGE_DOCUMENTS",
    ):
        assert forbidden not in actual
    app = manifest.find("application")
    assert app is not None and app.findall("provider") == []


def test_t_n4c_06_private_adapter_never_exported_as_mcp_file_manager() -> None:
    adapter = ADAPTER.read_text()
    for forbidden in (
        "startActivityForResult(",
        "registerForActivityResult(",
        "takePersistableUriPermission(",
        "openInputStream(",
        "openOutputStream(",
        "putExtra(",
        "requestPermissions(",
        "Log.",
    ):
        assert forbidden not in adapter
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidSafPickerProbe" not in gateway
    assert "NativeSafGrantPolicy" not in gateway

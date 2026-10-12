"""N0.e hardware-free Native artifact adapter/public-gateway guardrails."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ADAPTER = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/AndroidPrivateArtifacts.kt"
STORE = (
    ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle"
    / "NativeArtifactStore.kt"
)
GATEWAY = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_artifact_root_is_internal_no_backup_app_directory() -> None:
    source = ADAPTER.read_text()
    assert "context.noBackupFilesDir.toPath()" in source
    assert "NativeArtifactStore(" in source
    assert "Environment.getExternalStorageDirectory" not in source
    assert "getExternalFilesDir" not in source
    assert "intent.getStringExtra" not in source


def test_no_public_artifact_tool_or_exported_content_provider() -> None:
    gateway = GATEWAY.read_text()
    manifest = ET.parse(MANIFEST).getroot()
    app = manifest.find("application")
    assert app is not None
    assert app.findall("provider") == []
    assert app.attrib.get(ANDROID + "allowBackup") == "false"
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "NativeArtifactStore" not in gateway
    assert "artifact_download" not in gateway


def test_artifact_store_has_no_raw_diagnostic_or_external_network_path() -> None:
    source = STORE.read_text()
    assert "NativeArtifactStore" in source
    assert "StandardCopyOption.ATOMIC_MOVE" in source
    assert "FileChannel" in source
    assert "NOFOLLOW_LINKS" in source
    assert "PosixFilePermissions.fromString" in source
    assert "System.out." not in source
    assert "println(" not in source
    assert "Log." not in source
    assert "Socket(" not in source
    assert "Server(" not in source


def test_permissions_remain_exact_n3_allowlist() -> None:
    root = ET.parse(MANIFEST).getroot()
    declared = {node.get(ANDROID + "name") for node in root.findall("uses-permission")}
    assert declared == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }

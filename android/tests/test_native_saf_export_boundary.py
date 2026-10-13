"""N4.d source/Manifest/public-MCP SAF fake-export safety invariants."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidSafExportBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
MODEL = ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeSyntheticSafExport.kt"
GRANT = ROOT / "android/native-protocol/src/main/kotlin/org/androidmcp/protocol/NativeSafGrantPolicy.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
LOCK = ROOT / "android/native-lifecycle/gradle.lockfile"


def test_t_n4d_01_fake_read_is_bound_to_exact_user_selected_uri_before_provider() -> None:
    source = MODEL.read_text()
    assert "grants.matchesSelectedUri(" in source
    assert "SafAccessMode.READ" in source
    assert "document.uri != uri" in source
    assert "document.authority != trustedAuthority" in source
    assert "document.providerProcessId != trustedProviderProcessId" in source
    assert "NativeArtifactStore(" in source
    assert "store.create(bytes, outcome.mime)" in source
    assert "MessageDigest.isEqual" in source


def test_t_n4d_02_real_provider_and_unapproved_content_resolver_are_disabled() -> None:
    source = ADAPTER.read_text()
    assert "AndroidSafExportBoundary" in source
    assert "SafExportStatus.DENIED" in source
    for forbidden in (
        "openInputStream(",
        "openOutputStream(",
        "takePersistableUriPermission(",
        "openFileDescriptor(",
        "ContentResolver(",
        "startActivity(",
        "startActivityForResult(",
        "requestPermissions(",
        "Log.",
    ):
        assert forbidden not in source
    code = MODEL.read_text()
    assert "fun realContentResolverAccessAllowed(): Boolean = false" in code
    assert "SyntheticDocumentProvider" in code


def test_t_n4d_03_stream_limits_exception_safety_cancel_and_zeroing() -> None:
    source = MODEL.read_text()
    assert "MAX_BYTES = 1024 * 1024" in source
    assert "MAX_DOCUMENTS = 4" in source
    assert "TIMEOUT_MS = 1_500L" in source
    assert "ARTIFACT_TTL_MS = 60_000L" in source
    assert "cancelled.set(true)" in source
    assert "future.cancel(true)" in source
    assert "closeActiveStream()" in source
    assert "accumulator.fill(0)" in source
    assert "buffer.fill(0)" in source
    assert "bytes.fill(0)" in source
    assert "outcome.data?.fill(0)" in source
    assert "grants.check(request.grantHandle, SafAccessMode.READ)" in source


def test_t_n4d_04_process_scope_uses_hash_not_stored_raw_document_uri() -> None:
    source = MODEL.read_text()
    assert "selectedUriHash: ByteArray" in source
    assert "scopedUriHash(" in source
    assert "old.selectedUriHash" in source
    assert "override fun toString(): String = \"SafExportRequest([REDACTED])\"" in source
    assert "SyntheticDocument([REDACTED])" in source
    assert "artifact=[REDACTED]" in source
    assert "real_io_allowed" in source
    grant = GRANT.read_text()
    assert "selectedUriHash: ByteArray" in grant
    assert "fun matchesSelectedUri(" in grant


def test_t_n4d_05_no_public_storage_tool_or_broad_android_permissions() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidSafExportBoundary" not in gateway
    assert "NativeSyntheticSafExporter" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    actual = {x.get(ANDROID + "name") for x in manifest.findall("uses-permission")}
    assert actual == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    app = manifest.find("application")
    assert app is not None and app.findall("provider") == []


def test_t_n4d_06_new_module_dependency_is_locked_no_bypass() -> None:
    lock = LOCK.read_text()
    assert "kotlinx-serialization-json:1.9.0" in lock
    assert "kotlinx-serialization-core:1.9.0" in lock
    assert "testRuntimeClasspath" in lock
    gradle = ROOT / "android/native-lifecycle/build.gradle.kts"
    assert 'implementation(project(":native-protocol"))' in gradle.read_text()

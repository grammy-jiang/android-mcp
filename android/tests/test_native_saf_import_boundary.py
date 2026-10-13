"""N4.e SAF synthetic import plan: policy and source permission denials."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
APP = ROOT / "android/app/src/main/java/org/androidmcp/nativeapp"
ADAPTER = APP / "AndroidSafImportBoundary.kt"
GATEWAY = APP / "LocalMcpGateway.kt"
PLAN = ROOT / "android/native-lifecycle/src/main/kotlin/org/androidmcp/lifecycle/NativeSyntheticSafImport.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


def test_t_n4e_01_requires_hash_matching_owned_private_artifact_and_write_scope() -> None:
    code = PLAN.read_text()
    assert "grants.check(request.grantHandle, SafAccessMode.WRITE)" in code
    assert "grants.matchesSelectedUri(" in code
    assert "artifacts.read(request.artifactHandle)" in code
    assert "sha256(bytes)" in code
    assert "SafImportState.HASH_MISMATCH" in code
    assert "SafImportState.MISSING_ARTIFACT" in code
    assert "bytes.fill(0)" in code
    assert "request.expectedSha256" in code


def test_t_n4e_02_denies_foreign_provider_and_arbitrary_destination() -> None:
    code = PLAN.read_text()
    assert "request.providerAuthority != expectedAuthority" in code
    assert "request.providerProcessId != expectedProviderProcessId" in code
    assert "request.destinationUri" in code
    assert "SafAccessMode.WRITE" in code
    assert "SafImportState.WRONG_PROVIDER" in code
    assert "SafImportState.REVOKED" in code
    assert "SafImportState.EXPIRED" in code
    for forbidden in (
        "openOutputStream(",
        "openFileDescriptor(",
        "takePersistableUriPermission(",
        "FileOutputStream(",
        "ContentResolver(",
        "Runtime.getRuntime(",
        "ProcessBuilder(",
    ):
        assert forbidden not in code


def test_t_n4e_03_cancellation_is_uncertain_after_fake_dispatch_not_atomic() -> None:
    code = PLAN.read_text()
    assert "fakeDispatchStarted = true" in code
    assert "SafImportState.UNCERTAIN" in code
    assert "SafImportState.CANCELLED" in code
    assert "atomic_write_guaranteed" in code
    assert "false" in code
    assert "executed" in code
    assert "requires_fresh_user_consent" in code
    assert "fun realDocumentWriteAllowed(): Boolean = false" in code


def test_t_n4e_04_duplicate_reuse_not_overwriting_private_artifacts() -> None:
    code = PLAN.read_text()
    assert "MessageDigest.isEqual" in code
    assert "memo" in code
    assert "request.idempotencyKey" in code
    assert "expectedProviderProcessId" in code
    assert "NativeArtifactStore" in code
    assert "val epoch: String = UUID.randomUUID()" in code


def test_t_n4e_05_android_adapter_deny_by_default_no_saf_picker_started() -> None:
    source = ADAPTER.read_text()
    assert "internal object AndroidSafImportBoundary" in source
    assert "SafImportState.DENIED" in source
    assert "planId = null" in source
    for forbidden in (
        "openOutputStream(",
        "openInputStream(",
        "Intent.ACTION_CREATE_DOCUMENT",
        "startActivityForResult(",
        "registerForActivityResult(",
        "requestPermissions(",
        "takePersistableUriPermission(",
        "startActivity(",
    ):
        assert forbidden not in source


def test_t_n4e_06_manifest_mcp_public_tool_and_personal_content_not_exposed() -> None:
    gateway = GATEWAY.read_text()
    assert gateway.count("server.addTool(") == 1
    assert 'name = "device_status"' in gateway
    assert "AndroidSafImportBoundary" not in gateway
    assert "NativeSyntheticSafImportPlanner" not in gateway
    manifest = ET.parse(MANIFEST).getroot()
    permissions = {
        x.get(ANDROID + "name")
        for x in manifest.findall("uses-permission")
    }
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    }
    assert manifest.findall("queries") == []
    app = manifest.find("application")
    assert app is not None and app.findall("provider") == []

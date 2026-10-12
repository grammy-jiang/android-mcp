package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativePackageDetailsTest {
    private val target = "org.example.visible"
    private val visible = NativePackageVisibility.normalize(
        PackageVisibilityInput(apiLevel = 36),
        listOf(VisiblePackageCandidate(target, false, true))
    )
    private fun raw() = NativePackageDetailSource(
        packageName = target, installed = true, enabled = true,
        versionName = "1.2.3", versionCode = 1234,
        certificateSha256 = "ab".repeat(32), hasExportedActivity = true,
    )
    private fun query(
        request: NativePackageRequest = NativePackageRequest(target),
        source: NativePackageDetailSource? = raw(),
        scope: NativePackageVisibilitySnapshot = visible,
        api: Int = 36,
    ) = NativePackageDetails.resolve(api, request, scope, source)

    @Test
    fun tN2B01ExplicitVisibleIdGivesBoundedVersionCertDigestAndExportFlag() {
        val result = query()
        assertEquals(PackageDetailState.AVAILABLE, result.state)
        assertEquals(target, result.packageName)
        assertEquals("1.2.3", result.versionName)
        assertEquals(1234L, result.versionCode)
        assertEquals("ab".repeat(32), result.certificateSha256)
        assertEquals(true, result.hasExportedActivity)
        val payload = Json.parseToJsonElement(result.encode()).jsonObject
        assertEquals("1", payload.getValue("schema_version").jsonPrimitive.content)
        assertEquals("available", payload.getValue("availability").jsonPrimitive.content)
        assertEquals(target, payload.getValue("package_name").jsonPrimitive.content)
    }

    @Test
    fun tN2B02HiddenUnknownDisabledUninstalledAndWrongUserStatesAreExplicit() {
        val hidden = query(request = NativePackageRequest("org.hidden.app"))
        assertEquals(PackageDetailState.NOT_VISIBLE_OR_MISSING, hidden.state)
        assertNull(hidden.versionName)
        assertNull(query(source = null).versionName)
        assertEquals(PackageDetailState.NOT_VISIBLE_OR_MISSING, query(source = null).state)
        assertEquals(PackageDetailState.DISABLED, query(source = raw().copy(enabled = false)).state)
        assertEquals(PackageDetailState.UNINSTALLED, query(source = raw().copy(installed = false)).state)
        val wrongUser = query(request = NativePackageRequest(target, "work_profile"))
        assertEquals(PackageDetailState.WRONG_USER, wrongUser.state)
        assertNull(wrongUser.certificateSha256)
    }

    @Test
    fun tN2B03InvalidNamesControlCharsHugeLabelsAndPathsDeniedBeforeRead() {
        for (invalid in listOf(
            "", "org", "../data/user", "/sdcard/data", "org.example;reboot",
            "org.example\u0000app", "org." + "x".repeat(1000),
            "org.example..app", "org.example/hidden", "1org.bad", "org.example\nbad"
        )) {
            assertFalse(NativePackageDetails.validPackageName(invalid))
            val result = query(request = NativePackageRequest(invalid))
            assertEquals(PackageDetailState.DENIED, result.state)
            assertNull(result.packageName)
        }
        assertTrue(NativePackageDetails.validPackageName(target))
    }

    @Test
    fun tN2B04Api30_33_34_36StrictTypeAndNoBroadVisibility() {
        for (api in listOf(30, 33, 34, 36)) {
            val result = query(api = api)
            assertEquals(PackageDetailState.AVAILABLE, result.state)
            assertEquals(1234L, result.versionCode)
        }
        assertEquals(PackageDetailState.UNSUPPORTED, query(api = 29).state)
        val badCert = query(source = raw().copy(certificateSha256 = "private-key"))
        assertEquals(PackageDetailState.PARTIAL, badCert.state)
        assertNull(badCert.certificateSha256)
        assertEquals(PackageDetailState.PARTIAL,
            query(source = raw().copy(versionCode = Long.MAX_VALUE)).state)
    }

    @Test
    fun tN2B05FreshVisibilityOrPackageStateChangeRejectsCachedFacts() {
        val vanishedVisibility = NativePackageVisibility.normalize(
            PackageVisibilityInput(36), emptyList()
        )
        assertEquals(PackageDetailState.NOT_VISIBLE_OR_MISSING,
            query(scope = vanishedVisibility, source = raw()).state)
        val policyDenied = NativePackageVisibility.normalize(
            PackageVisibilityInput(36, broadPermissionDeclared = true), emptyList()
        )
        assertEquals(PackageDetailState.DENIED, query(scope = policyDenied, source = raw()).state)
        assertEquals(PackageDetailState.DISABLED, query(source = raw().copy(enabled = false)).state)
        assertNull(query(scope = vanishedVisibility, source = raw()).certificateSha256)
    }

    @Test
    fun tN2B06VersionedOutputAndSensitiveInformationNeverLeakUnauthenticated() {
        val compromised = query(source = raw().copy(
            versionName = "secret-token-app-account",
            certificateSha256 = "private-signature-key"
        ))
        val output = compromised.encode().lowercase()
        assertTrue(output.toByteArray().size <= 4096)
        for (needle in listOf("token", "account", "private_key", "signature", "serial",
            "filesystem", "path", "permission_grants", "user_id", "imei"
        )) assertFalse(output.contains(needle))
        val guard = NativeLocalCallerGuard()
        assertFalse(guard.authorizeSensitive(LocalHttpRequest(), "native_package_details").allowed)
        assertFalse(NativeLocalStatus.encode().contains("certificate_sha256"))
    }

    @Test
    fun unrelatedPackageManagerResultIsRejectedBeforeMetadataExposure() {
        val mismatched = query(source = raw().copy(packageName = "org.someone.else"))
        assertEquals(PackageDetailState.DENIED, mismatched.state)
        assertNull(mismatched.versionName)
        assertNull(mismatched.certificateSha256)
    }

    @Test
    fun malformedVersionAndUppercaseDigestAreNormalizedWithoutRawCerts() {
        val transformed = query(source = raw().copy(
            versionName = "1.2.3\ncredentials-not-logged",
            certificateSha256 = "AB".repeat(32),
        ))
        assertEquals(PackageDetailState.PARTIAL, transformed.state)
        assertNull(transformed.versionName)
        assertEquals("ab".repeat(32), transformed.certificateSha256)
        assertFalse(transformed.encode().contains("credentials"))
    }
}

package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.TimeUnit

class NativePackageVisibilityTest {
    private fun candidate(name: String) = VisiblePackageCandidate(name, false, true)
    private val approved = PackageVisibilityInput(apiLevel = 36)

    @Test
    fun tN2A01FilteredVisibleAppsSortedDedupedAndBounded() {
        val candidates = listOf(
            candidate("org.visible.z"),
            candidate("org.visible.a"),
            candidate("org.visible.z"),
            candidate("org.visible.b"),
        )
        val result = NativePackageVisibility.normalize(approved, candidates)
        assertEquals(PackageVisibilityState.FILTERED, result.state)
        assertTrue(result.visibilityRestricted)
        assertEquals(listOf("org.visible.a", "org.visible.b", "org.visible.z"),
            result.visibleApps.map { it.packageName })
        assertFalse(result.truncated)
        assertEquals(VisiblePackageLookup.VISIBLE, result.lookup("org.visible.b"))
        val root = Json.parseToJsonElement(result.encode()).jsonObject
        assertEquals(1, root.getValue("schema_version").jsonPrimitive.content.toInt())
        assertEquals("android_filtered_package_manager",
            root.getValue("scope").jsonPrimitive.content)
        assertEquals(3, root.getValue("apps").jsonArray.size)
    }

    @Test
    fun tN2A02NotVisibleDoesNotMeanPackageDoesNotExistOnAnySupportedApi() {
        for (api in listOf(30, 33, 34, 36)) {
            val visible = NativePackageVisibility.normalize(
                approved.copy(apiLevel = api), listOf(candidate("org.visible.one"))
            )
            assertTrue(visible.visibilityRestricted)
            assertEquals(PackageVisibilityState.FILTERED, visible.state)
            assertEquals(VisiblePackageLookup.NOT_VISIBLE_OR_MISSING,
                visible.lookup("org.hidden.possibly.installed"))
            assertFalse(visible.encode().contains("NOT_FOUND"))
        }
        val old = NativePackageVisibility.normalize(
            approved.copy(apiLevel = 29), listOf(candidate("org.visible.one"))
        )
        assertEquals(PackageVisibilityState.UNSUPPORTED, old.state)
        assertTrue(old.visibleApps.isEmpty())
    }

    @Test
    fun tN2A03BroadVisibilityAndCrossUserEnumerationDeniedByPolicy() {
        for (bad in listOf(
            approved.copy(broadPermissionDeclared = true),
            approved.copy(crossUserRequested = true),
            approved.copy(broadPermissionDeclared = true, crossUserRequested = true),
        )) {
            val result = NativePackageVisibility.normalize(bad,
                listOf(candidate("org.other.app")))
            assertEquals(PackageVisibilityState.DENIED, result.state)
            assertTrue(result.visibleApps.isEmpty())
            assertEquals(VisiblePackageLookup.DENIED, result.lookup("org.other.app"))
        }
    }

    @Test
    fun tN2A04MalformedHugeListAndSlowPlatformCallAreBounded() {
        val huge = (0..1200).map { candidate("org.safe.package$it") }
        val normal = NativePackageVisibility.normalize(approved, huge)
        assertTrue(normal.truncated)
        assertTrue(normal.visibleApps.size <= 64)
        assertEquals(PackageVisibilityState.PARTIAL, normal.state)
        val invalid = NativePackageVisibility.normalize(
            approved, listOf(candidate("../data/token"), candidate("org.safe.ok"), candidate("bad;name"))
        )
        assertEquals(listOf("org.safe.ok"), invalid.visibleApps.map { it.packageName })
        val start = System.nanoTime()
        NativePackageVisibilitySampler().use { sampler ->
            val unavailable = sampler.sample(approved, 75) {
                Thread.sleep(2000)
                listOf(candidate("org.never.returned"))
            }
            assertEquals(PackageVisibilityState.UNAVAILABLE, unavailable.state)
            assertTrue(unavailable.visibleApps.isEmpty())
        }
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start) < 1500)
    }

    @Test
    fun tN2A05UnpairedLocalCallerCannotEnumerateEvenFilteredApps() {
        val policy = NativeToolProfiles()
        assertEquals(listOf("device_status"), policy.liveTools(true).map { it.name })
        val guard = NativeLocalCallerGuard()
        assertFalse(guard.authorizeSensitive(LocalHttpRequest(),
            "native_visible_packages").allowed)
        assertFalse(guard.authorizeSensitive(LocalHttpRequest(origin = "http://127.0.0.1:38765"),
            "native_visible_packages", SyntheticCallerApproval(guard.epoch, "nonce", true)).allowed)
        assertFalse(NativeLocalStatus.encode().contains("packages"))
    }

    @Test
    fun tN2A06VersionedVisiblePackageResultsNeverLeakAccountsOrSignatures() {
        val result = NativePackageVisibility.normalize(approved, listOf(
            candidate("org.visible.app"), candidate("secret=credential.password"),
            candidate("org.example.token=abc")
        ))
        val output = result.encode().lowercase()
        assertEquals(1, result.visibleApps.size)
        for (secret in listOf(
            "account", "password", "token=", "private_key", "signature",
            "permission_grants", "filepath", "device_id", "serial",
        )) assertFalse(output.contains(secret))
        assertTrue(output.toByteArray().size <= 16_384)
        assertEquals(VisiblePackageLookup.NOT_VISIBLE_OR_MISSING,
            result.lookup("org.example.token=abc"))
    }

    @Test
    fun missingAppInfoOrOemSecurityExceptionCannotInventVisibility() {
        val incomplete = NativePackageVisibility.normalize(
            approved,
            listOf(
                VisiblePackageCandidate("org.safe.visible", null, true),
                VisiblePackageCandidate("org.safe.good", false, true),
            ),
        )
        assertEquals(PackageVisibilityState.PARTIAL, incomplete.state)
        assertEquals(listOf("org.safe.good"), incomplete.visibleApps.map { it.packageName })
        NativePackageVisibilitySampler().use { sampler ->
            val failure = sampler.sample(approved, 200) {
                throw SecurityException("private OEM app list, must not leak")
            }
            assertEquals(PackageVisibilityState.UNAVAILABLE, failure.state)
            assertTrue(failure.visibleApps.isEmpty())
            assertFalse(failure.encode().contains("private OEM"))
        }
    }

    @Test
    fun closedSamplerRefusesFurtherPlatformCalls() {
        val sampler = NativePackageVisibilitySampler()
        sampler.close()
        val denied = sampler.sample(approved, 100) {
            throw AssertionError("Closed sampler must not invoke PackageManager")
        }
        assertEquals(PackageVisibilityState.UNAVAILABLE, denied.state)
        assertEquals(VisiblePackageLookup.DENIED, denied.lookup("org.example.app"))
    }
}

package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativePackageInstallerPlanTest {
    private val packageName = "org.example.safeapp"
    private val apk = "a".repeat(64)
    private val cert = "b".repeat(64)
    private fun artifact() = SyntheticApkArtifact(
        handle = "s".repeat(32), packageName = packageName,
        abi = "arm64-v8a", minSdk = 30, targetSdk = 30,
        apkSha256 = apk, signingCertSha256 = cert, bytes = 4096,
    )
    private fun env(api: Int = 36, unknownSourcesAllowed: Boolean? = false) =
        NativeInstallerPlanEnvironment(
            apiLevel = api, nativeAbi = "arm64-v8a",
            allowedPackages = setOf(packageName), pinnedApkDigests = setOf(apk),
            trustedSigningCerts = setOf(cert), unknownSourcesAllowed = unknownSourcesAllowed,
        )
    private fun request() = SyntheticInstallPlanRequest(artifact(), "req-install-001")

    @Test
    fun tN7A01TrustedPinnedApkYieldsDeterministicUserMediatedPlanOnly() {
        val first = NativePackageInstallerPlans(env()).plan(request())
        val second = NativePackageInstallerPlans(env()).plan(request())
        assertEquals(NativeInstallPlanStatus.PLAN_ONLY, first.status)
        assertEquals(first.planId, second.planId)
        assertNotNull(first.planId)
        assertEquals(64, first.planId!!.length)
        assertTrue(first.requiresUserConfirmation)
        assertFalse(first.installationPerformed)
        assertFalse(first.installerSessionOpened)
    }

    @Test
    fun tN7A02UnsignedForgedCertInvalidTargetAndArbitraryFileUriRejected() {
        val bad = listOf(
            artifact().copy(signed = false), artifact().copy(signingCertSha256 = "c".repeat(64)),
            artifact().copy(apkSha256 = "d".repeat(64)),
            artifact().copy(targetSdk = 29), artifact().copy(minSdk = 37),
            artifact().copy(privateArtifactPresent = false),
            artifact().copy(sourceUri = "file:///data/local/tmp/other.apk"),
            artifact().copy(handle = "../../outside/apk"),
        )
        for ((i, candidate) in bad.withIndex()) {
            val got = NativePackageInstallerPlans(env()).plan(
                request().copy(requestId = "bad-$i", artifact = candidate),
            )
            assertFalse(got.status == NativeInstallPlanStatus.PLAN_ONLY)
            assertFalse(got.installationPerformed)
            assertNull(got.planId)
        }
    }

    @Test
    fun tN7A03ModelClaimsSilentInstallOrBroadInstallPermissionCannotBypass() {
        val planner = NativePackageInstallerPlans(env())
        val hostile = listOf(
            request().copy(installWithoutPrompt = true),
            request().copy(requestBroadInstallPermission = true),
            request().copy(callerVerified = false, approvedByModel = true),
            request().copy(schemaVersion = 99),
        )
        hostile.forEach { assertFalse(planner.plan(it).status == NativeInstallPlanStatus.PLAN_ONLY) }
        assertEquals(NativeInstallPlanStatus.PLAN_ONLY,
            planner.plan(request().copy(approvedByModel = true)).status)
        assertFalse(planner.realInstallerEnabled())
    }

    @Test
    fun tN7A04Api30To36RequiresActualAndroidUserConsentUnknownSourcesNeverGranted() {
        for (api in listOf(30, 33, 34, 36)) {
            val missing = NativePackageInstallerPlans(env(api)).plan(request())
            assertEquals(NativeInstallPlanStatus.PLAN_ONLY, missing.status)
            assertTrue(missing.requiresUnknownSourcesSettings)
            assertTrue(missing.requiresUserConfirmation)
            assertFalse(missing.unknownSourcesGranted)
            val allowed = NativePackageInstallerPlans(env(api, true)).plan(request())
            assertFalse(allowed.requiresUnknownSourcesSettings)
            assertTrue(allowed.requiresUserConfirmation)
            assertFalse(allowed.unknownSourcesGranted)
            assertFalse(allowed.installationPerformed)
        }
        assertEquals(NativeInstallPlanStatus.UNSUPPORTED,
            NativePackageInstallerPlans(env(29)).plan(request()).status)
    }

    @Test
    fun tN7A05CancellationReplayAndStopNeverCreateInstallerSession() {
        val planner = NativePackageInstallerPlans(env())
        val approved = planner.plan(request())
        assertEquals(NativeInstallPlanStatus.PLAN_ONLY, approved.status)
        assertEquals(NativeInstallPlanStatus.CANCELLED, planner.cancel(approved.planId!!))
        assertEquals(NativeInstallPlanStatus.REPLAY_DENIED, planner.plan(request()).status)
        assertEquals(NativeInstallPlanStatus.CANCELLED, planner.cancel(approved.planId!!))
        planner.stop()
        assertEquals(NativeInstallPlanStatus.STOPPED,
            planner.plan(request().copy(requestId = "fresh-install-002")).status)
        assertEquals(0, planner.activeInstallerSessions())
        assertFalse(planner.realInstallerEnabled())
    }

    @Test
    fun tN7A06DefaultLiveToolAndReceiptNeverAdvertiseExecutionOrSilentGrant() {
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        val planner = NativePackageInstallerPlans(env())
        val result = planner.plan(request())
        assertFalse(result.installationPerformed)
        assertFalse(result.installerSessionOpened)
        assertFalse(result.unknownSourcesGranted)
        assertTrue(result.encode().contains("\"installation_performed\":false"))
        assertTrue(result.encode().contains("\"automatic_retry\":false"))
        assertFalse(result.encode().contains(packageName))
        assertFalse(result.encode().contains(apk))
        assertFalse(planner.realInstallerEnabled())
    }

    @Test
    fun boundedPlansDoNotEvictOldOneTimeRequests() {
        val planner = NativePackageInstallerPlans(env())
        for (n in 1..64) {
            val original = request().copy(requestId = "plan-$n")
            assertEquals(NativeInstallPlanStatus.PLAN_ONLY, planner.plan(original).status)
        }
        assertEquals(NativeInstallPlanStatus.UNAVAILABLE,
            planner.plan(request().copy(requestId = "plan-65")).status)
        assertEquals(NativeInstallPlanStatus.REPLAY_DENIED,
            planner.plan(request().copy(requestId = "plan-1")).status)
        assertFalse(planner.realInstallerEnabled())
        assertEquals(0, planner.activeInstallerSessions())
    }

    @Test
    fun hostilePlanningInputsCannotLeakPrivateMetadataOrCreateSession() {
        val planner = NativePackageInstallerPlans(env())
        val badRequests = listOf(
            request().copy(requestId = "invalid request"),
            request().copy(artifact = artifact().copy(abi = "x86_64")),
            request().copy(artifact = artifact().copy(bytes = -1)),
            request().copy(artifact = artifact().copy(bytes = 1024L * 1024L * 1024L + 1)),
            request().copy(artifact = artifact().copy(packageName = "org.other.untrusted")),
        )
        for (bad in badRequests) {
            assertFalse(planner.plan(bad).status == NativeInstallPlanStatus.PLAN_ONLY)
        }
        val original = request()
        assertFalse(original.toString().contains(packageName))
        assertFalse(original.artifact.toString().contains(cert))
        val result = planner.plan(original)
        assertEquals(NativeInstallPlanStatus.PLAN_ONLY, result.status)
        assertFalse(result.encode().contains(original.artifact.handle))
        assertFalse(result.encode().contains(cert))
        assertTrue(result.encode().toByteArray().size < 1024)
        assertEquals(0, planner.activeInstallerSessions())
    }

    @Test
    fun parallelSyntheticPlannerCannotIssueMultiplePlansForSameRequest() {
        val planner = NativePackageInstallerPlans(env())
        val pool = java.util.concurrent.Executors.newFixedThreadPool(12)
        val begin = java.util.concurrent.CountDownLatch(1)
        try {
            val results = (1..12).map {
                pool.submit<NativeInstallPlanReceipt> {
                    begin.await(5, java.util.concurrent.TimeUnit.SECONDS)
                    planner.plan(request())
                }
            }
            begin.countDown()
            val receipts = results.map { it.get(5, java.util.concurrent.TimeUnit.SECONDS) }
            assertEquals(1, receipts.count { it.status == NativeInstallPlanStatus.PLAN_ONLY })
            assertEquals(11, receipts.count { it.status == NativeInstallPlanStatus.REPLAY_DENIED })
            assertEquals(0, planner.activeInstallerSessions())
        } finally { begin.countDown(); pool.shutdownNow() }
    }
}

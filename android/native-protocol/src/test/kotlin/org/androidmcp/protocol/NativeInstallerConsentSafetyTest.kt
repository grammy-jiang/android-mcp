package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeInstallerConsentSafetyTest {
    private fun req(api: Int = 36): FakeInstallerConsentRequest =
        FakeInstallerConsentRequest(
            emulator = FakeInstallerEmulatorProof(
                serial = "emulator-5554", expectedApi = api, observedApi = api,
                qemuKernel = true, bootComplete = true, ownedDisposable = true,
            ),
            requestId = "signed-test-001", signedTestArtifact = true,
            trustedTestPackage = true, apiUnknownSourcesAllowed = false,
        )

    @Test
    fun tN7B01EmulatorEligibilityCannotClaimRealConsentUiWasOpened() {
        val policy = NativeInstallerConsentSafety()
        val eligible = policy.preflight(req())
        assertEquals(NativeInstallerConsentStatus.ELIGIBLE_EMULATOR_ONLY, eligible.status)
        assertTrue(eligible.requiresVisibleOsConsent)
        assertFalse(eligible.consentUiOpened)
        assertFalse(eligible.installed)
        assertEquals(NativeInstallerConsentStatus.BLOCKED,
            policy.attemptConsentUi(req()).status)
    }

    @Test
    fun tN7B02RefusalAndCancellationNeverInstallOrLeaveSession() {
        val policy = NativeInstallerConsentSafety()
        assertEquals(NativeInstallerConsentStatus.REFUSED, policy.refuse().status)
        val cancelled = policy.cancel()
        assertEquals(NativeInstallerConsentStatus.CANCELLED, cancelled.status)
        assertFalse(cancelled.installed)
        assertFalse(cancelled.sessionOpened)
        assertEquals(0, policy.activeSessions())
    }

    @Test
    fun tN7B03PhysicalOrUnknownOrUnownedEmulatorRejectedBeforeAnyAction() {
        val variants = listOf(
            req().copy(emulator = req().emulator.copy(serial = "R3CT505P6EK")),
            req().copy(emulator = req().emulator.copy(qemuKernel = false)),
            req().copy(emulator = req().emulator.copy(observedApi = 30)),
            req().copy(emulator = req().emulator.copy(ownedDisposable = false)),
            req().copy(emulator = req().emulator.copy(bootComplete = false)),
            req().copy(trustedTestPackage = false),
            req().copy(signedTestArtifact = false),
        )
        for (variant in variants) {
            val policy = NativeInstallerConsentSafety()
            assertEquals(NativeInstallerConsentStatus.REJECTED_TARGET,
                policy.preflight(variant).status)
            assertFalse(policy.realInstallerEnabled())
            assertEquals(0, policy.activeSessions())
        }
    }

    @Test
    fun tN7B04ForegroundLostDeathAndStopInvalidateFakePendingSession() {
        val policy = NativeInstallerConsentSafety()
        assertEquals(NativeInstallerConsentStatus.REJECTED_TARGET,
            policy.preflight(req().copy(ownActivityForeground = false)).status)
        assertEquals(NativeInstallerConsentStatus.ABANDONED, policy.processDeath().status)
        policy.stop()
        assertEquals(NativeInstallerConsentStatus.STOPPED, policy.preflight(req()).status)
        assertEquals(0, policy.activeSessions())
        assertFalse(policy.realInstallerEnabled())
    }

    @Test
    fun tN7B05AllFourApiLevelsRequireVisibleConsentAndSeparateUnknownSources() {
        for (api in listOf(30, 33, 34, 36)) {
            val policy = NativeInstallerConsentSafety()
            val needed = policy.preflight(req(api))
            assertEquals(NativeInstallerConsentStatus.ELIGIBLE_EMULATOR_ONLY, needed.status)
            assertTrue(needed.requiresUnknownSourcesSettings)
            assertTrue(needed.requiresVisibleOsConsent)
            assertFalse(needed.installed)
            val fakeAllowed = policy.preflight(req(api).copy(apiUnknownSourcesAllowed = true,
                requestId = "different-$api"))
            assertFalse(fakeAllowed.requiresUnknownSourcesSettings)
            assertTrue(fakeAllowed.requiresVisibleOsConsent)
            assertFalse(fakeAllowed.consentUiOpened)
        }
        assertEquals(NativeInstallerConsentStatus.REJECTED_TARGET,
            NativeInstallerConsentSafety().preflight(req(29)).status)
    }

    @Test
    fun tN7B06ProductionToolAndPermissionStateNeverEnableSilentInstall() {
        val policy = NativeInstallerConsentSafety()
        assertEquals(listOf("device_status"), NativeToolProfiles().publicTools().map { it.name })
        assertFalse(policy.realInstallerEnabled())
        assertFalse(policy.attemptConsentUi(req().copy(modelApproved = true)).installed)
        assertEquals(0, policy.activeSessions())
    }
}

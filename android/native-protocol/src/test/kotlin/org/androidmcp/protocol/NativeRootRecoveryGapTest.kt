package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeRootRecoveryGapTest {
    private fun goodEnv() = SyntheticRootRecoveryEnvironment()
    private fun request(surface: RootRecoverySurface = RootRecoverySurface.HOST_SAFE_TRIAGE) =
        SyntheticRootRecoveryRequest(surface)

    @Test
    fun tN8B01OrdinaryNativeAppCannotRootUnlockBootloaderOrFlashRom() {
        val policy = NativeRootRecoveryGap()
        val gaps = policy.inspectOrdinaryAppCapabilities()
        for (capability in listOf(
            RootRecoverySurface.ROOT, RootRecoverySurface.BOOTLOADER, RootRecoverySurface.ROM_FLASH,
        )) {
            assertEquals(RootRecoveryState.UNSUPPORTED, gaps[capability])
            assertEquals(RootRecoveryState.UNSUPPORTED,
                policy.evaluate(goodEnv(), request(capability)).status)
        }
        assertFalse(policy.realRootOrFlashAllowed())
    }

    @Test
    fun tN8B02NativeProductionToolsNeverExposeRawShellFastbootOrPartitionWriters() {
        val policy = NativeRootRecoveryGap()
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        assertEquals(RootRecoveryState.DENIED,
            policy.evaluate(goodEnv(), request(RootRecoverySurface.RAW_SHELL)).status)
        assertEquals(RootRecoveryState.DENIED,
            policy.evaluate(goodEnv(), request(RootRecoverySurface.UNLOCK_BOOTLOADER)).status)
        assertFalse(policy.realRootOrFlashAllowed())
    }

    @Test
    fun tN8B03UnbootableOrCrashedNativeCannotClaimItCanRecoverItselfRemotely() {
        val policy = NativeRootRecoveryGap()
        for (unavailable in listOf(
            goodEnv().copy(nativeBootable = false),
            goodEnv().copy(nativeServiceOnline = false),
        )) {
            val result = policy.evaluate(unavailable, request())
            assertEquals(RootRecoveryState.UNAVAILABLE, result.status)
            assertTrue(result.manualHostFallbackRequired)
            assertFalse(result.operationExecuted)
        }
    }

    @Test
    fun tN8B04ForgedHostOrMissingAdbFastbootAuthorizationCannotEscalate() {
        val policy = NativeRootRecoveryGap()
        val scenarios = listOf(
            goodEnv().copy(hostIdentityVerified = false),
            goodEnv().copy(hostId = "foreign host"),
            goodEnv().copy(adbAuthorized = false),
            goodEnv().copy(physicalOwnerPresent = false),
            goodEnv().copy(ownerConfirmed = false),
        )
        for (scenario in scenarios) {
            assertEquals(RootRecoveryState.BLOCKED, policy.evaluate(scenario, request()).status)
        }
        assertEquals(RootRecoveryState.BLOCKED,
            policy.evaluate(goodEnv().copy(fastbootAuthorized = false),
                request(RootRecoverySurface.HOST_SAFE_RECOVERY_GUIDANCE)).status)
        assertFalse(policy.realRootOrFlashAllowed())
    }

    @Test
    fun tN8B05ModelBypassLockscreenEraseDataAndUnlockAttemptsFailClosed() {
        val policy = NativeRootRecoveryGap()
        for (action in listOf(
            RootRecoverySurface.LOCKSCREEN_BYPASS,
            RootRecoverySurface.ERASE_USER_DATA,
            RootRecoverySurface.UNLOCK_BOOTLOADER,
            RootRecoverySurface.RAW_SHELL,
        )) {
            assertEquals(RootRecoveryState.DENIED,
                policy.evaluate(goodEnv(), request(action)).status)
        }
        assertEquals(RootRecoveryState.DENIED,
            policy.evaluate(goodEnv(), request().copy(requestedCommand = "arbitrary command")).status)
        assertEquals(RootRecoveryState.DENIED,
            policy.evaluate(goodEnv(), request().copy(bypassSecurity = true)).status)
    }

    @Test
    fun tN8B06SafeHostSupervisedPlanRequiresPhysicalOwnerAndExecutesNothing() {
        val policy = NativeRootRecoveryGap()
        val plan = policy.evaluate(goodEnv(), request())
        assertEquals(RootRecoveryState.PLAN_ONLY, plan.status)
        assertTrue(plan.requiresPhysicalOwnerConfirmation)
        assertTrue(plan.manualHostFallbackRequired)
        assertTrue(plan.safeNextSteps.any { it.contains("owner", ignoreCase = true) })
        assertTrue(plan.safeNextSteps.any { it.contains("Host", ignoreCase = true) })
        assertFalse(plan.operationExecuted)
        assertTrue(plan.encode().contains("\"operation_executed\":false"))
        assertTrue(plan.encode().contains("\"automatic_retry\":false"))
        assertFalse(policy.realRootOrFlashAllowed())
    }

    @Test
    fun boundedManualPlanCannotReplayOrOverridePastOwnerConsent() {
        val policy = NativeRootRecoveryGap()
        for (n in 1..32) {
            assertEquals(RootRecoveryState.PLAN_ONLY,
                policy.evaluate(goodEnv(), request().copy(requestId = "safe-$n")).status)
        }
        assertEquals(RootRecoveryState.REPLAY_DENIED,
            policy.evaluate(goodEnv(), request().copy(requestId = "safe-1")).status)
        assertEquals(RootRecoveryState.BLOCKED,
            policy.evaluate(goodEnv(), request().copy(requestId = "safe-33")).status)
        assertFalse(policy.realRootOrFlashAllowed())
        policy.stop()
        assertEquals(RootRecoveryState.STOPPED,
            policy.evaluate(goodEnv(), request().copy(requestId = "new-after-stop")).status)
    }

    @Test
    fun manualGuidanceRedactsHostAndNeverContainsExecutableCommands() {
        val policy = NativeRootRecoveryGap()
        val environment = goodEnv().copy(hostId = "hostPRIVATEtoken01")
        val result = policy.evaluate(environment,
            request(RootRecoverySurface.HOST_SAFE_RECOVERY_GUIDANCE))
        assertEquals(RootRecoveryState.PLAN_ONLY, result.status)
        val output = result.encode().lowercase()
        assertTrue(output.toByteArray().size < 2048)
        assertFalse(output.contains("hostprivatetoken"))
        assertFalse(output.contains("shell"))
        assertFalse(output.contains("reboot"))
        assertFalse(output.contains("flash "))
        assertFalse(output.contains("serial"))
        assertFalse(output.contains("\"operation_executed\":true"))
        assertFalse(environment.toString().contains(environment.hostId))
    }

    @Test
    fun fakeAuthorizedHostNeverExecutesPrivilegedActionAcrossAllApis() {
        for (api in listOf(30, 33, 34, 36)) {
            val policy = NativeRootRecoveryGap()
            assertEquals(RootRecoveryState.PLAN_ONLY,
                policy.evaluate(goodEnv().copy(apiLevel = api), request()).status)
            assertEquals(RootRecoveryState.UNSUPPORTED,
                policy.evaluate(goodEnv().copy(apiLevel = api),
                    request(RootRecoverySurface.ROM_FLASH)).status)
            assertFalse(policy.realRootOrFlashAllowed())
        }
        assertEquals(RootRecoveryState.UNSUPPORTED,
            NativeRootRecoveryGap().evaluate(goodEnv().copy(apiLevel = 29), request()).status)
    }
}

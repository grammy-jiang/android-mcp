package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeProjectionConsentTest {
    private fun environment(
        api: Int = 36,
        hasManager: Boolean = true,
        hasMediaProjectionFgsType: Boolean = false,
        foreground: Boolean = true,
    ) = ProjectionEnvironment(api, hasManager, hasMediaProjectionFgsType, foreground)

    @Test
    fun tN3A01UnavailableOrWithoutUserConsentIsDeniedWithTruthfulPlan() {
        val readySystem = NativeProjectionConsent(environment(hasMediaProjectionFgsType = true))
        val request = readySystem.plan()
        assertEquals(ProjectionConsentStatus.CONSENT_REQUIRED, request.status)
        assertTrue(request.requiresVisibleUserConsent)
        assertTrue(request.mediaProjectionFgsTypeRequired)
        assertFalse(request.canCaptureNow)
        assertFalse(readySystem.captureAllowed())
        val missing = NativeProjectionConsent(environment(hasManager = false)).plan()
        assertEquals(ProjectionConsentStatus.UNAVAILABLE, missing.status)
        assertFalse(missing.canCaptureNow)
        val json = Json.parseToJsonElement(request.encode()).jsonObject
        assertEquals("1", json.getValue("schema_version").jsonPrimitive.content)
        assertEquals("consent_required", json.getValue("status").jsonPrimitive.content)
    }

    @Test
    fun tN3A02Api34And36SyntheticPerSessionTokenCannotReplayOrForge() {
        for (api in listOf(34, 36)) {
            val policy = NativeProjectionConsent(environment(api = api, hasMediaProjectionFgsType = true))
            val grant = SyntheticProjectionGrant(policy.processEpoch, "nonce-abc", true)
            assertEquals(ProjectionConsentStatus.SIMULATED_ONLY, policy.recognizeSynthetic(grant))
            assertFalse(policy.captureAllowed())
            assertTrue(policy.syntheticSessionActive())
            assertEquals(ProjectionConsentStatus.REPLAY_DENIED, policy.recognizeSynthetic(grant))
            val next = NativeProjectionConsent(environment(api = api, hasMediaProjectionFgsType = true))
            assertNotEquals(policy.processEpoch, next.processEpoch)
            assertEquals(ProjectionConsentStatus.STALE_DENIED, next.recognizeSynthetic(grant))
            assertEquals(ProjectionConsentStatus.DENIED,
                next.recognizeSynthetic(grant.copy(fakeUiConsentGranted = false, processEpoch = next.processEpoch)))
            assertFalse(next.captureAllowed())
        }
    }

    @Test
    fun tN3A03Api30_33Vs34_36FgServiceTypeNotSilentlyDeclared() {
        for (api in listOf(30, 33)) {
            val policy = NativeProjectionConsent(environment(api))
            assertEquals(ProjectionConsentStatus.CONSENT_REQUIRED, policy.plan().status)
            assertFalse(policy.plan().mediaProjectionFgsTypeRequired)
            assertFalse(policy.plan().canCaptureNow)
        }
        for (api in listOf(34, 36)) {
            val policy = NativeProjectionConsent(environment(api))
            assertEquals(ProjectionConsentStatus.FGS_TYPE_REQUIRED, policy.plan().status)
            assertTrue(policy.plan().mediaProjectionFgsTypeRequired)
            assertTrue(policy.plan().requiresVisibleUserConsent)
            assertFalse(policy.captureAllowed())
        }
        assertEquals(ProjectionConsentStatus.UNSUPPORTED,
            NativeProjectionConsent(environment(api = 29)).plan().status)
    }

    @Test
    fun tN3A04RefusalLockScreenOffActivityDeathAndFgsStopRevokeImmediately() {
        for (event in ProjectionLifecycleEvent.entries) {
            val session = NativeProjectionConsent(environment(hasMediaProjectionFgsType = true))
            val grant = SyntheticProjectionGrant(session.processEpoch, "fresh-nonce", true)
            assertEquals(ProjectionConsentStatus.SIMULATED_ONLY, session.recognizeSynthetic(grant))
            session.event(event)
            assertFalse(session.syntheticSessionActive())
            assertFalse(session.captureAllowed())
            assertEquals(ProjectionConsentStatus.REVOKED,
                session.recognizeSynthetic(grant.copy(nonce = "new-nonce")))
        }
    }

    @Test
    fun tN3A05UnrelatedProcessOriginOrCallerNeverActivatesCapture() {
        val policy = NativeProjectionConsent(environment(hasMediaProjectionFgsType = true))
        val wrongEpoch = SyntheticProjectionGrant("forged-other-process", "nonce", true)
        assertEquals(ProjectionConsentStatus.STALE_DENIED, policy.recognizeSynthetic(wrongEpoch))
        val guard = NativeLocalCallerGuard()
        val spoof = SyntheticCallerApproval(guard.epoch, "fake", true)
        for (caller in listOf(
            LocalHttpRequest(origin = null),
            LocalHttpRequest(origin = "https://evil.example"),
            LocalHttpRequest(remoteHost = "192.0.2.2"),
        )) assertFalse(guard.authorizeSensitive(caller, "native_screen_capture", spoof).allowed)
        assertFalse(policy.captureAllowed())
    }

    @Test
    fun tN3A06FakeConsentIsNeverARealGrantOrNewPublicTool() {
        val policy = NativeProjectionConsent(environment(hasMediaProjectionFgsType = true))
        val fake = SyntheticProjectionGrant(policy.processEpoch, "only-fake", true)
        assertEquals(ProjectionConsentStatus.SIMULATED_ONLY, policy.recognizeSynthetic(fake))
        assertFalse(policy.plan().canCaptureNow)
        assertFalse(policy.captureAllowed())
        assertFalse(NativeToolProfiles().liveTools(true).any { it.name.contains("capture") })
        assertFalse(NativeLocalStatus.encode().contains("media_projection"))
        assertFalse(policy.plan().encode().contains("token"))
        assertTrue(policy.plan().encode().length < 2048)
    }

    @Test
    fun syntheticNonceValidationAndReplayCapacityNeverActivateRealCapture() {
        val policy = NativeProjectionConsent(environment(hasMediaProjectionFgsType = true))
        for (nonce in listOf("", "bad\nnonce", "x".repeat(129))) {
            assertEquals(ProjectionConsentStatus.DENIED,
                policy.recognizeSynthetic(SyntheticProjectionGrant(policy.processEpoch, nonce, true)))
        }
        for (index in 0 until 256) {
            assertEquals(ProjectionConsentStatus.SIMULATED_ONLY,
                policy.recognizeSynthetic(SyntheticProjectionGrant(
                    policy.processEpoch, "synthetic-$index", true,
                )))
            assertFalse(policy.captureAllowed())
        }
        assertEquals(ProjectionConsentStatus.DENIED,
            policy.recognizeSynthetic(SyntheticProjectionGrant(policy.processEpoch, "overflow", true)))
        assertFalse(policy.captureAllowed())
    }

    @Test
    fun foregroundAndManagerMissingDenyEvenCorrectEpochFakeConsent() {
        for (env in listOf(
            environment(hasManager = false, hasMediaProjectionFgsType = true),
            environment(foreground = false, hasMediaProjectionFgsType = true),
            environment(api = 29, hasMediaProjectionFgsType = true),
            environment(api = 36, hasMediaProjectionFgsType = false),
        )) {
            val policy = NativeProjectionConsent(env)
            assertEquals(ProjectionConsentStatus.DENIED,
                policy.recognizeSynthetic(SyntheticProjectionGrant(policy.processEpoch, "n", true)))
            assertFalse(policy.syntheticSessionActive())
            assertFalse(policy.captureAllowed())
        }
    }
}

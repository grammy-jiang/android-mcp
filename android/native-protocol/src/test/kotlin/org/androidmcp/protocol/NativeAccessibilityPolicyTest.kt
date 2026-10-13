package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeAccessibilityPolicyTest {
    private fun setup(
        api: Int = 36,
        declared: Boolean = false,
        enabled: Boolean = false,
        connected: Boolean = false,
        foreground: Boolean = true,
        unlocked: Boolean = true,
        purpose: AccessibilityPurpose = AccessibilityPurpose.VISIBLE_UI_INSPECTION,
    ) = AccessibilityEnvironment(
        api, declared, enabled, connected, foreground, unlocked, purpose,
    )
    private fun ready() = setup(declared = true, enabled = true, connected = true)
    private fun permit(policy: NativeAccessibilityPolicy) = SyntheticAccessibilityPermit(
        epoch = policy.epoch, nonce = "fake-approval-1",
        fakeApprovedByUser = true, fakeAuthenticatedCaller = true,
    )

    @Test
    fun tN3D01DisabledByDefaultNeedsExplicitUserActivation() {
        val policy = NativeAccessibilityPolicy(setup())
        val decision = policy.plan()
        assertEquals(AccessibilityEligibility.SERVICE_NOT_DECLARED, decision.state)
        assertFalse(decision.settingsUserActionRequired) // no service to enable
        assertFalse(decision.uiInspectionAvailable)
        assertFalse(decision.uiActionAvailable)
        assertFalse(policy.liveUiInspectionAllowed())
        assertFalse(policy.liveUiActionAllowed())
        val planned = NativeAccessibilityPolicy(setup(declared = true))
        assertEquals(AccessibilityEligibility.USER_ACTIVATION_REQUIRED, planned.plan().state)
        assertTrue(planned.plan().settingsUserActionRequired)
    }

    @Test
    fun tN3D02UserRefusalNeverBecomesAndroidSettingsGrant() {
        val policy = NativeAccessibilityPolicy(ready())
        assertEquals(AccessibilityEligibility.SIMULATED_ONLY,
            policy.recognizeFake(permit(policy)))
        policy.revoke(AccessibilityLifecycleEvent.USER_REFUSED)
        assertEquals(AccessibilityEligibility.REVOKED, policy.plan().state)
        assertFalse(policy.fakeSessionActive())
        assertFalse(policy.liveUiInspectionAllowed())
        assertFalse(policy.liveUiActionAllowed())
        assertEquals(AccessibilityEligibility.REVOKED,
            policy.recognizeFake(permit(policy).copy(nonce = "new-fake")))
    }

    @Test
    fun tN3D03MissingManifestServiceOverrulesAllForgedPositiveFlags() {
        for (api in listOf(30, 33, 34, 36)) {
            val policy = NativeAccessibilityPolicy(
                setup(api, declared = false, enabled = true, connected = true)
            )
            assertEquals(AccessibilityEligibility.SERVICE_NOT_DECLARED, policy.plan().state)
            assertEquals(AccessibilityEligibility.DENIED, policy.recognizeFake(permit(policy)))
            assertFalse(policy.fakeSessionActive())
            assertFalse(policy.liveUiInspectionAllowed())
        }
    }

    @Test
    fun tN3D04AndroidApiMatrixPurposeAndForegroundRestrictionsFailClosed() {
        for (api in listOf(30, 33, 34, 36)) {
            val supported = NativeAccessibilityPolicy(ready().copy(apiLevel = api))
            assertEquals(AccessibilityEligibility.USER_ACTIVATION_REQUIRED, supported.plan().state)
            assertFalse(supported.plan().uiInspectionAvailable)
            assertFalse(supported.plan().uiActionAvailable)
        }
        assertEquals(AccessibilityEligibility.UNSUPPORTED,
            NativeAccessibilityPolicy(ready().copy(apiLevel = 29)).plan().state)
        assertEquals(AccessibilityEligibility.POLICY_DISABLED,
            NativeAccessibilityPolicy(ready().copy(reviewedUserPurpose = AccessibilityPurpose.NONE))
                .plan().state)
        assertEquals(AccessibilityEligibility.UNAVAILABLE,
            NativeAccessibilityPolicy(ready().copy(foreground = false)).plan().state)
        assertEquals(AccessibilityEligibility.LOCKED,
            NativeAccessibilityPolicy(ready().copy(screenUnlocked = false)).plan().state)
    }

    @Test
    fun tN3D05RevokedDisconnectedLockedOrHostileCallerClearsFakeNodes() {
        for (event in AccessibilityLifecycleEvent.entries) {
            val policy = NativeAccessibilityPolicy(ready())
            assertEquals(AccessibilityEligibility.SIMULATED_ONLY, policy.recognizeFake(permit(policy)))
            policy.revoke(event)
            assertEquals(AccessibilityEligibility.REVOKED, policy.plan().state)
            assertFalse(policy.fakeSessionActive())
            assertFalse(policy.liveUiInspectionAllowed())
            assertEquals(AccessibilityEligibility.REVOKED,
                policy.recognizeFake(permit(policy).copy(nonce = "other-nonce")))
        }
        val old = NativeAccessibilityPolicy(ready())
        val next = NativeAccessibilityPolicy(ready())
        assertNotEquals(old.epoch, next.epoch)
        assertEquals(AccessibilityEligibility.STALE_DENIED, next.recognizeFake(permit(old)))
        assertEquals(AccessibilityEligibility.DENIED,
            next.recognizeFake(permit(next).copy(fakeAuthenticatedCaller = false)))
        assertFalse(next.liveUiActionAllowed())
    }

    @Test
    fun tN3D06DefaultV1RegistryAndPolicyNeverEnablePrivilegedService() {
        val policy = NativeAccessibilityPolicy(ready())
        val fake = permit(policy)
        assertEquals(AccessibilityEligibility.SIMULATED_ONLY, policy.recognizeFake(fake))
        assertEquals(AccessibilityEligibility.REPLAY_DENIED, policy.recognizeFake(fake))
        assertFalse(policy.liveUiInspectionAllowed())
        assertFalse(policy.liveUiActionAllowed())
        val encoded = policy.plan().encode()
        val fields = Json.parseToJsonElement(encoded).jsonObject
        assertEquals("1", fields.getValue("schema_version").jsonPrimitive.content)
        assertEquals("false", fields.getValue("ui_action_available").jsonPrimitive.content)
        assertFalse(encoded.contains("private"))
        assertTrue(encoded.length < 1024)
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        assertFalse(NativeLocalStatus.encode().contains("accessibility_nodes"))
    }

    @Test
    fun syntheticNonceBoundsAndCapacityPreventInfiniteReplays() {
        val policy = NativeAccessibilityPolicy(ready())
        for (nonce in listOf("", "bad\nnonce", "X".repeat(129))) {
            assertEquals(AccessibilityEligibility.DENIED, policy.recognizeFake(
                permit(policy).copy(nonce = nonce),
            ))
            assertFalse(policy.fakeSessionActive())
        }
        for (index in 0 until 256) {
            assertEquals(AccessibilityEligibility.SIMULATED_ONLY,
                policy.recognizeFake(permit(policy).copy(nonce = "test-$index")))
            assertFalse(policy.liveUiInspectionAllowed())
            assertFalse(policy.liveUiActionAllowed())
        }
        assertEquals(AccessibilityEligibility.DENIED,
            policy.recognizeFake(permit(policy).copy(nonce = "overflow")))
    }

    @Test
    fun disconnectedOrNotUserEnabledCannotPretendToBeApproved() {
        for (environment in listOf(
            ready().copy(userEnabled = false),
            ready().copy(serviceConnected = false),
            ready().copy(screenUnlocked = false),
            ready().copy(foreground = false),
            ready().copy(reviewedUserPurpose = AccessibilityPurpose.NONE),
        )) {
            val policy = NativeAccessibilityPolicy(environment)
            assertEquals(AccessibilityEligibility.DENIED, policy.recognizeFake(permit(policy)))
            assertFalse(policy.fakeSessionActive())
            assertFalse(policy.liveUiActionAllowed())
        }
    }
}

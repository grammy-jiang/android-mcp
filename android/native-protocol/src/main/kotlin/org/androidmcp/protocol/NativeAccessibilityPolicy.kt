package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/**
 * N3.d user-visible, default-OFF Accessibility eligibility policy only.
 *
 * Neither a fake consent nor an Android app's own Service declaration can
 * grant Accessibility privileges. No Settings write, service activation,
 * UI node access, or gesture dispatch exists in this module.
 */
enum class AccessibilityEligibility {
    SERVICE_NOT_DECLARED, USER_ACTIVATION_REQUIRED, CONSENT_REFUSED,
    POLICY_DISABLED, UNSUPPORTED, LOCKED, UNAVAILABLE, SIMULATED_ONLY,
    STALE_DENIED, REPLAY_DENIED, REVOKED, DENIED
}

enum class AccessibilityPurpose { NONE, VISIBLE_UI_INSPECTION, USER_ASSISTANCE }

enum class AccessibilityLifecycleEvent {
    USER_REFUSED, USER_DISABLED, SERVICE_DISCONNECTED,
    FOREGROUND_STOP, SCREEN_LOCKED, PROCESS_DEATH,
}

data class AccessibilityEnvironment(
    val apiLevel: Int,
    val serviceDeclared: Boolean,
    val userEnabled: Boolean,
    val serviceConnected: Boolean,
    val foreground: Boolean,
    val screenUnlocked: Boolean,
    val reviewedUserPurpose: AccessibilityPurpose,
)

data class AccessibilityEligibilityPlan(
    val schemaVersion: Int,
    val state: AccessibilityEligibility,
    val settingsUserActionRequired: Boolean,
    val uiInspectionAvailable: Boolean,
    val uiActionAvailable: Boolean,
) {
    /** Fixed public-safe, privilege-free plan; no node text or credentials. */
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("status", state.name.lowercase())
        put("requires_user_settings_action", settingsUserActionRequired)
        put("ui_inspection_available", false)
        put("ui_action_available", false)
        put("live_service_activation", false)
    }.toString()
}

/** Test-only fixture that is never read from HTTP, an Intent extra or MCP. */
data class SyntheticAccessibilityPermit(
    val epoch: String,
    val nonce: String,
    val fakeApprovedByUser: Boolean,
    val fakeAuthenticatedCaller: Boolean,
)

/**
 * Process-scoped in-memory synthetic approval that cannot create a
 * production AccessibilityService. Any termination permanently revokes it.
 * Another session or Android process may not reuse a fake nonce or epoch.
 */
class NativeAccessibilityPolicy(private val environment: AccessibilityEnvironment) {
    val epoch: String = UUID.randomUUID().toString()
    private var revoked = false
    private var simulatedActive = false
    private val usedNonces = HashSet<String>()

    @Synchronized
    fun plan(): AccessibilityEligibilityPlan {
        val eligibleApi = environment.apiLevel in 30..100
        val state = when {
            !eligibleApi -> AccessibilityEligibility.UNSUPPORTED
            revoked -> AccessibilityEligibility.REVOKED
            !environment.serviceDeclared -> AccessibilityEligibility.SERVICE_NOT_DECLARED
            environment.reviewedUserPurpose == AccessibilityPurpose.NONE ->
                AccessibilityEligibility.POLICY_DISABLED
            !environment.foreground -> AccessibilityEligibility.UNAVAILABLE
            !environment.screenUnlocked -> AccessibilityEligibility.LOCKED
            // Even enabled/connected fake input never means that the
            // production app has an authorized Accessibility instance.
            else -> AccessibilityEligibility.USER_ACTIVATION_REQUIRED
        }
        return AccessibilityEligibilityPlan(
            schemaVersion = 1,
            state = state,
            // A missing AccessibilityService declaration cannot be repaired
            // by a user toggling Settings: no service exists to activate.
            settingsUserActionRequired = eligibleApi && !revoked &&
                environment.serviceDeclared && !environment.userEnabled &&
                state == AccessibilityEligibility.USER_ACTIVATION_REQUIRED,
            uiInspectionAvailable = false,
            uiActionAvailable = false,
        )
    }

    @Synchronized
    fun recognizeFake(permit: SyntheticAccessibilityPermit): AccessibilityEligibility {
        if (revoked) return AccessibilityEligibility.REVOKED
        if (permit.epoch != epoch) return AccessibilityEligibility.STALE_DENIED
        if (!permit.fakeApprovedByUser || !permit.fakeAuthenticatedCaller) {
            return AccessibilityEligibility.DENIED
        }
        if (permit.nonce.length !in 1..128 ||
            permit.nonce.any { it.code !in 0x21..0x7E }
        ) return AccessibilityEligibility.DENIED
        if (permit.nonce in usedNonces) return AccessibilityEligibility.REPLAY_DENIED
        if (plan().state != AccessibilityEligibility.USER_ACTIVATION_REQUIRED ||
            !environment.userEnabled || !environment.serviceConnected
        ) return AccessibilityEligibility.DENIED
        if (usedNonces.size >= 256) return AccessibilityEligibility.DENIED
        usedNonces.add(permit.nonce)
        simulatedActive = true
        return AccessibilityEligibility.SIMULATED_ONLY
    }

    @Suppress("UNUSED_PARAMETER")
    @Synchronized
    fun revoke(event: AccessibilityLifecycleEvent) {
        revoked = true
        simulatedActive = false
    }

    @Synchronized
    fun fakeSessionActive(): Boolean = simulatedActive && !revoked

    /** Explicitly impossible to authorize production UI reads or gestures. */
    fun liveUiInspectionAllowed(): Boolean = false
    fun liveUiActionAllowed(): Boolean = false
}

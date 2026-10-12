package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/**
 * Only inert MediaProjection consent planning. Neither a fake approval nor an
 * Android MediaProjection token is accepted as live capture authorization.
 */
enum class ProjectionConsentStatus {
    CONSENT_REQUIRED, FGS_TYPE_REQUIRED, UNAVAILABLE, UNSUPPORTED,
    SIMULATED_ONLY, REPLAY_DENIED, STALE_DENIED, REVOKED, DENIED
}

enum class ProjectionLifecycleEvent {
    USER_REFUSED, SCREEN_LOCKED, SCREEN_OFF, ACTIVITY_DESTROYED, FGS_STOP,
    SYSTEM_PROJECTION_STOP, PROCESS_DEATH
}

data class ProjectionEnvironment(
    val apiLevel: Int,
    val projectionManagerPresent: Boolean,
    val mediaProjectionFgsTypeDeclared: Boolean,
    val callerForeground: Boolean,
)

data class ProjectionConsentPlan(
    val schemaVersion: Int,
    val status: ProjectionConsentStatus,
    val requiresVisibleUserConsent: Boolean,
    val mediaProjectionFgsTypeRequired: Boolean,
    val canCaptureNow: Boolean,
) {
    /**
     * Fixed public-safe guidance with no MediaProjection Intent, token,
     * screenshot, user/device identifier, or synthetic proof serialized.
     */
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("status", status.name.lowercase())
        put("requires_visible_user_consent", requiresVisibleUserConsent)
        put("media_projection_fgs_type_required", mediaProjectionFgsTypeRequired)
        put("can_capture_now", false)
    }.toString()
}

/** Local unit-test input; never convert from HTTP, JSON, Origin or app extras. */
data class SyntheticProjectionGrant(
    val processEpoch: String,
    val nonce: String,
    val fakeUiConsentGranted: Boolean,
)

/**
 * A per-instance inert policy, not an Android MediaProjectionManager wrapper.
 * MediaProjection consent must be requested and consumed by a future,
 * independently reviewed Activity/session with genuine Android OS UI.
 */
class NativeProjectionConsent(private val environment: ProjectionEnvironment) {
    val processEpoch: String = UUID.randomUUID().toString()
    private var revoked = false
    private var simulatedActive = false
    private val usedNonces = HashSet<String>()

    @Synchronized
    fun plan(): ProjectionConsentPlan {
        val supports = environment.apiLevel in 30..100
        val fgsRequired = environment.apiLevel >= 34 && supports
        val status = when {
            !supports -> ProjectionConsentStatus.UNSUPPORTED
            revoked -> ProjectionConsentStatus.REVOKED
            !environment.projectionManagerPresent -> ProjectionConsentStatus.UNAVAILABLE
            !environment.callerForeground -> ProjectionConsentStatus.DENIED
            fgsRequired && !environment.mediaProjectionFgsTypeDeclared ->
                ProjectionConsentStatus.FGS_TYPE_REQUIRED
            else -> ProjectionConsentStatus.CONSENT_REQUIRED
        }
        return ProjectionConsentPlan(
            schemaVersion = 1,
            status = status,
            requiresVisibleUserConsent = supports &&
                environment.projectionManagerPresent && !revoked,
            mediaProjectionFgsTypeRequired = fgsRequired,
            canCaptureNow = false,
        )
    }

    @Synchronized
    fun recognizeSynthetic(grant: SyntheticProjectionGrant): ProjectionConsentStatus {
        if (revoked) return ProjectionConsentStatus.REVOKED
        if (grant.processEpoch != processEpoch) return ProjectionConsentStatus.STALE_DENIED
        if (!grant.fakeUiConsentGranted) return ProjectionConsentStatus.DENIED
        if (grant.nonce.length !in 1..128 ||
            grant.nonce.any { it.code < 0x21 || it.code > 0x7E }
        ) return ProjectionConsentStatus.DENIED
        if (grant.nonce in usedNonces) return ProjectionConsentStatus.REPLAY_DENIED
        if (plan().status != ProjectionConsentStatus.CONSENT_REQUIRED) {
            return ProjectionConsentStatus.DENIED
        }
        // Bound stored synthetic replay markers; never persist live tokens.
        if (usedNonces.size >= 256) return ProjectionConsentStatus.DENIED
        usedNonces.add(grant.nonce)
        simulatedActive = true
        return ProjectionConsentStatus.SIMULATED_ONLY
    }

    @Synchronized
    fun event(event: ProjectionLifecycleEvent) {
        // Every user/platform termination event is terminal for this session.
        // Even a later fake nonce cannot resurrect capture readiness.
        revoked = true
        simulatedActive = false
    }

    @Synchronized
    fun captureAllowed(): Boolean = false

    @Synchronized
    fun syntheticSessionActive(): Boolean = simulatedActive && !revoked
}

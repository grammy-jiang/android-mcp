package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N7.c: synthetic *explicit* app launch planning with one-use action IDs.
 * Real startActivity, shell, FGS background-start bypass and third-party
 * app interaction do NOT exist in the production Native MCP app.
 */
enum class SafeLaunchState {
    PLANNED, DENIED, REVOKED, LOCKED, BACKGROUND_RESTRICTED,
    REPLAY_DENIED, UNCERTAIN, CANCELLED, STOPPED, UNSUPPORTED,
}

data class SyntheticSafeLaunchRequest(
    val intent: NativeIntentRequest,
    val actionId: String,
    val authorizedCaller: Boolean,
    val userApproved: Boolean,
    val signedGrantFresh: Boolean,
    val screenUnlocked: Boolean,
    val originRevoked: Boolean = false,
    val foregroundServiceOnly: Boolean = false,
) {
    override fun toString() = "SyntheticSafeLaunchRequest([REDACTED])"
}

data class SyntheticSafeLaunchTarget(
    val environment: NativeLaunchEnvironment,
    val visibility: NativePackageVisibilitySnapshot,
    val target: NativeResolvedActivity?,
    val explicitAllowlist: Set<String>,
    val ownDisposableQemu: Boolean,
) {
    override fun toString() = "SyntheticSafeLaunchTarget([REDACTED])"
}

data class SafeLaunchReceipt(
    val status: SafeLaunchState,
    val planId: String? = null,
) {
    val realLaunched: Boolean = false
    val realDispatchAllowed: Boolean = false

    /** Redacted, truthful; digest/action IDs and package details are absent. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("real_launched", false)
        put("real_dispatch_allowed", false)
        put("synthetic_only", true)
        put("idempotent", false)
        put("automatic_retry", false)
        put("requires_fresh_user_grant", true)
    }.toString()
}

/**
 * The pure Kotlin T-N7C model cannot authenticate QEMU or user approval.
 * Fake fixtures are never deserialized from public MCP/HTTP or Android Intent.
 * The real local Native MCP Tool registry remains status-only and writes OFF.
 */
class NativeExplicitLaunchSafety {
    private var revoked = false
    private var stopped = false
    private val actionPlans = LinkedHashMap<String, String>()
    private val uncertainPlans = HashSet<String>()

    @Synchronized
    fun plan(
        request: SyntheticSafeLaunchRequest,
        platform: SyntheticSafeLaunchTarget,
    ): SafeLaunchReceipt {
        fun deny(state: SafeLaunchState) = SafeLaunchReceipt(state)
        if (stopped) return deny(SafeLaunchState.STOPPED)
        if (revoked || request.originRevoked || !request.authorizedCaller ||
            !request.userApproved || !request.signedGrantFresh
        ) return deny(SafeLaunchState.REVOKED)
        if (!request.screenUnlocked) return deny(SafeLaunchState.LOCKED)
        if (platform.environment.apiLevel !in SUPPORTED_API) {
            return deny(SafeLaunchState.UNSUPPORTED)
        }
        if (!platform.ownDisposableQemu || !ACTION_ID.matches(request.actionId)) {
            return deny(SafeLaunchState.DENIED)
        }
        if (!platform.environment.callerForeground ||
            !platform.environment.userGestureObserved || request.foregroundServiceOnly
        ) return deny(SafeLaunchState.BACKGROUND_RESTRICTED)
        val existing = NativeIntentPlans.resolve(
            request.intent, platform.environment, platform.visibility,
            platform.explicitAllowlist, platform.target,
        )
        when (existing.state) {
            NativeIntentPlanState.UNSUPPORTED -> return deny(SafeLaunchState.UNSUPPORTED)
            NativeIntentPlanState.BACKGROUND_RESTRICTED ->
                return deny(SafeLaunchState.BACKGROUND_RESTRICTED)
            NativeIntentPlanState.PLAN_ONLY -> Unit
            else -> return deny(SafeLaunchState.DENIED)
        }
        val planId = existing.planId ?: return deny(SafeLaunchState.DENIED)
        if (planId in uncertainPlans) return deny(SafeLaunchState.UNCERTAIN)
        if (request.actionId in actionPlans) return deny(SafeLaunchState.REPLAY_DENIED)
        if (actionPlans.size >= MAX_ACTIONS) return deny(SafeLaunchState.DENIED)
        actionPlans[request.actionId] = planId
        return SafeLaunchReceipt(SafeLaunchState.PLANNED, planId)
    }

    /**
     * Even this marker performs NO real dispatch. A post-dispatch-like
     * ambiguity records a permanent digest tombstone to forbid auto replay.
     */
    @Synchronized
    fun markFakeDispatch(
        actionId: String,
        platform: SyntheticSafeLaunchTarget,
        ownerStillApproves: Boolean = true,
        originStillAuthorized: Boolean = true,
    ): SafeLaunchReceipt {
        fun deny(state: SafeLaunchState) = SafeLaunchReceipt(state)
        if (stopped) return deny(SafeLaunchState.STOPPED)
        if (revoked || !ownerStillApproves || !originStillAuthorized) {
            return deny(SafeLaunchState.REVOKED)
        }
        if (!platform.ownDisposableQemu || !platform.environment.callerForeground ||
            !platform.environment.userGestureObserved
        ) return deny(SafeLaunchState.BACKGROUND_RESTRICTED)
        val planId = actionPlans[actionId] ?: return deny(SafeLaunchState.DENIED)
        if (planId in uncertainPlans) return deny(SafeLaunchState.UNCERTAIN)
        uncertainPlans.add(planId)
        return deny(SafeLaunchState.UNCERTAIN)
    }

    @Synchronized
    fun revoke() {
        revoked = true
    }

    @Synchronized
    fun stop() {
        stopped = true
    }

    fun activeRealLaunchCount(): Int = 0
    fun realLaunchAllowed(): Boolean = false

    companion object {
        private val SUPPORTED_API = setOf(30, 33, 34, 36)
        private const val MAX_ACTIONS = 64
        private val ACTION_ID = Regex("[A-Za-z0-9_-]{1,128}")
    }
}

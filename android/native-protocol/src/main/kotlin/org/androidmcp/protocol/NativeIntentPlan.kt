package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.security.MessageDigest

/** N2.c purely deterministic, never launches an Activity or grants access. */
enum class NativeIntentPlanState {
    PLAN_ONLY, DENIED, NOT_VISIBLE_OR_MISSING, NOT_EXPORTED,
    BACKGROUND_RESTRICTED, UNSUPPORTED, UNAVAILABLE
}

data class NativeIntentRequest(
    val packageName: String,
    val activityName: String,
    val action: String = "android.intent.action.MAIN",
    val category: String = "android.intent.category.LAUNCHER",
    val userScope: String = "current",
    val uri: String? = null,
    val extras: Map<String, String> = emptyMap(),
    val flags: Int = 0,
    val selector: Boolean = false,
)

data class NativeResolvedActivity(
    val packageName: String,
    val activityName: String,
    val exported: Boolean,
    val enabled: Boolean,
)

data class NativeLaunchEnvironment(
    val apiLevel: Int,
    val callerForeground: Boolean,
    val userGestureObserved: Boolean,
)

data class NativeIntentPlanResult(
    val state: NativeIntentPlanState,
    val packageName: String?,
    val activityName: String?,
    val action: String?,
    val planId: String?,
    val requiresSeparateUserGrant: Boolean,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("availability", state.name.lowercase())
        put("package_name", packageName?.let(::JsonPrimitive) ?: JsonNull)
        put("activity_name", activityName?.let(::JsonPrimitive) ?: JsonNull)
        put("action", action?.let(::JsonPrimitive) ?: JsonNull)
        put("plan_id", planId?.let(::JsonPrimitive) ?: JsonNull)
        put("requires_separate_user_grant", requiresSeparateUserGrant)
        put("executed", false)
    }.toString()
}

/**
 * Deny by default. Even a PLAN_ONLY descriptor never authorizes startActivity.
 * A fresh user consent and separately reviewed identity are required for
 * future execution. Intent URI, grants, extras and selectors are forbidden.
 */
object NativeIntentPlans {
    private val COMPONENT = Regex("[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)+")
    private const val ACTION_MAIN = "android.intent.action.MAIN"
    private const val CATEGORY_LAUNCHER = "android.intent.category.LAUNCHER"


    fun preflight(
        request: NativeIntentRequest,
        environment: NativeLaunchEnvironment,
        allowlistedComponents: Set<String>,
    ): NativeIntentPlanState? {
        if (environment.apiLevel !in 30..100) return NativeIntentPlanState.UNSUPPORTED
        if (request.userScope != "current" ||
            request.packageName.length !in 3..160 ||
            !NativePackageDetails.validPackageName(request.packageName) ||
            request.activityName.length !in 3..200 ||
            !COMPONENT.matches(request.activityName) ||
            !request.activityName.startsWith(request.packageName + ".") ||
            request.action != ACTION_MAIN || request.category != CATEGORY_LAUNCHER ||
            request.uri != null || request.extras.isNotEmpty() ||
            request.flags != 0 || request.selector
        ) return NativeIntentPlanState.DENIED
        if (request.packageName + "/" + request.activityName !in allowlistedComponents) {
            return NativeIntentPlanState.DENIED
        }
        if (!environment.callerForeground || !environment.userGestureObserved) {
            return NativeIntentPlanState.BACKGROUND_RESTRICTED
        }
        return null
    }

    fun unavailable(): NativeIntentPlanResult = NativeIntentPlanResult(
        NativeIntentPlanState.UNAVAILABLE, null, null, null, null, false,
    )

    fun resolve(
        request: NativeIntentRequest,
        environment: NativeLaunchEnvironment,
        visible: NativePackageVisibilitySnapshot,
        allowlistedComponents: Set<String>,
        target: NativeResolvedActivity?,
    ): NativeIntentPlanResult {
        fun denied(reason: NativeIntentPlanState) =
            NativeIntentPlanResult(reason, null, null, null, null, false)

        val preflight = preflight(request, environment, allowlistedComponents)
        if (preflight != null) return denied(preflight)
        if (visible.lookup(request.packageName) != VisiblePackageLookup.VISIBLE) {
            return denied(NativeIntentPlanState.NOT_VISIBLE_OR_MISSING)
        }
        if (target == null) return denied(NativeIntentPlanState.NOT_VISIBLE_OR_MISSING)
        if (target.packageName != request.packageName ||
            target.activityName != request.activityName || !target.enabled
        ) return denied(NativeIntentPlanState.DENIED)
        if (!target.exported) return denied(NativeIntentPlanState.NOT_EXPORTED)
        if (!environment.callerForeground || !environment.userGestureObserved) {
            return denied(NativeIntentPlanState.BACKGROUND_RESTRICTED)
        }

        val component = request.packageName + "/" + request.activityName
        // A public identity checksum, never a capability token.
        val digest = MessageDigest.getInstance("SHA-256")
            .digest((component + "|" + ACTION_MAIN + "|" + CATEGORY_LAUNCHER + "|v1")
                .toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        return NativeIntentPlanResult(
            state = NativeIntentPlanState.PLAN_ONLY,
            packageName = request.packageName,
            activityName = request.activityName,
            action = ACTION_MAIN,
            planId = digest,
            requiresSeparateUserGrant = true,
        )
    }
}

/** Read-only platform-resolve probe. There is intentionally no launch method. */
fun interface VisibleActivityResolver {
    fun resolve(request: NativeIntentRequest): NativeResolvedActivity?
}

object NativeIntentPlanner {
    /** No probe call for invalid, unauthorized, stale-visibility or background requests. */
    fun plan(
        request: NativeIntentRequest,
        environment: NativeLaunchEnvironment,
        visibility: NativePackageVisibilitySnapshot,
        allowlistedComponents: Set<String>,
        resolver: VisibleActivityResolver,
    ): NativeIntentPlanResult {
        val preflight = NativeIntentPlans.preflight(request, environment, allowlistedComponents)
        if (preflight != null ||
            visibility.lookup(request.packageName) != VisiblePackageLookup.VISIBLE
        ) {
            return NativeIntentPlans.resolve(
                request, environment, visibility, allowlistedComponents, null,
            )
        }
        return try {
            val observed = resolver.resolve(request)
            NativeIntentPlans.resolve(request, environment, visibility, allowlistedComponents, observed)
        } catch (_: RuntimeException) {
            NativeIntentPlans.unavailable()
        }
    }
}

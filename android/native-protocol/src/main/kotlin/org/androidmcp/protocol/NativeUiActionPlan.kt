package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.security.MessageDigest

/**
 * N4.a inert, read-only action planning. The Android production APK never
 * dispatches Accessibility gestures or key events from this model.
 */
enum class UiActionKind { TAP, SWIPE, SCROLL, KEY }
enum class UiScrollDirection { UP, DOWN }
enum class UiAllowedKey { ENTER, BACK, TAB, DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT }
enum class UiActionPlanState {
    PLAN_ONLY, DENIED, STALE, OUT_OF_BOUNDS, ROTATION_MISMATCH,
    SERVICE_UNAVAILABLE, LOCKED, UNAUTHENTICATED, UNSUPPORTED,
    CANCELLED, UNCERTAIN,
}

data class UiActionIntent(
    val kind: UiActionKind,
    val windowHandle: String,
    val nodeEpoch: String,
    val nodeHandle: String,
    val rotation: Int,
    val x: Int? = null,
    val y: Int? = null,
    val endX: Int? = null,
    val endY: Int? = null,
    val durationMs: Int? = null,
    val direction: UiScrollDirection? = null,
    val steps: Int? = null,
    val key: UiAllowedKey? = null,
    val shellText: String? = null,
)

data class UiActionEnvironment(
    val apiLevel: Int,
    val focusedWindowHandle: String,
    val nodeEpoch: String,
    val currentRotation: Int,
    val displayWidth: Int,
    val displayHeight: Int,
    val fakeAccessibilityAvailable: Boolean,
    val fakeCallerAuthenticated: Boolean,
    val fakeUserApproval: Boolean,
    val foreground: Boolean,
    val screenUnlocked: Boolean,
    val secureWindow: Boolean = false,
    val currentNodeHandles: Set<String> = emptySet(),
)

data class UiActionPlanResult(
    val state: UiActionPlanState,
    val digest: String?,
    val requiresFreshAuthorization: Boolean,
    val idempotent: Boolean,
) {
    /** A deterministic checksum is NOT a replayable execution credential. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", state.name.lowercase())
        put("digest", digest?.let(::JsonPrimitive) ?: JsonNull)
        put("requires_fresh_authorization", requiresFreshAuthorization)
        put("idempotent", false)
        put("executed", false)
        put("synthetic_only", true)
    }.toString()
}

/**
 * Fixed typed plans anchored to one window, one ephemeral node epoch, one
 * rotation and one display. No shell, implicit key, text injection, home key,
 * or gesture executor is reachable from this pure Kotlin object.
 */
object NativeUiActionPlans {
    private val HANDLE = Regex("[a-f0-9]{32}")
    private val EPOCH = Regex("[A-Za-z0-9_-]{8,64}")

    fun resolve(
        intent: UiActionIntent,
        environment: UiActionEnvironment,
    ): UiActionPlanResult {
        fun fail(state: UiActionPlanState) =
            UiActionPlanResult(state, null, false, false)

        if (environment.apiLevel !in 30..100) return fail(UiActionPlanState.UNSUPPORTED)
        if (!environment.fakeCallerAuthenticated || !environment.fakeUserApproval) {
            return fail(UiActionPlanState.UNAUTHENTICATED)
        }
        if (!environment.fakeAccessibilityAvailable) {
            return fail(UiActionPlanState.SERVICE_UNAVAILABLE)
        }
        if (!environment.screenUnlocked || environment.secureWindow) {
            return fail(UiActionPlanState.LOCKED)
        }
        if (!environment.foreground) return fail(UiActionPlanState.DENIED)
        if (!HANDLE.matches(intent.windowHandle) ||
            !HANDLE.matches(intent.nodeHandle) ||
            !EPOCH.matches(intent.nodeEpoch) ||
            !HANDLE.matches(environment.focusedWindowHandle) ||
            !EPOCH.matches(environment.nodeEpoch)
        ) return fail(UiActionPlanState.DENIED)
        if (environment.nodeEpoch != intent.nodeEpoch ||
            environment.focusedWindowHandle != intent.windowHandle ||
            intent.nodeHandle !in environment.currentNodeHandles
        ) return fail(UiActionPlanState.STALE)
        if (environment.currentRotation !in 0..3 || intent.rotation !in 0..3 ||
            environment.currentRotation != intent.rotation
        ) return fail(UiActionPlanState.ROTATION_MISMATCH)
        if (environment.displayWidth !in 1..4096 ||
            environment.displayHeight !in 1..8192 ||
            environment.displayWidth.toLong() * environment.displayHeight > 16_777_216
        ) return fail(UiActionPlanState.OUT_OF_BOUNDS)
        if (intent.shellText != null) return fail(UiActionPlanState.DENIED)

        val valid = when (intent.kind) {
            UiActionKind.TAP -> {
                validCoord(intent.x, intent.y, environment) &&
                    intent.endX == null && intent.endY == null &&
                    intent.durationMs == null && intent.direction == null &&
                    intent.steps == null && intent.key == null
            }
            UiActionKind.SWIPE -> {
                validCoord(intent.x, intent.y, environment) &&
                    validCoord(intent.endX, intent.endY, environment) &&
                    intent.durationMs in 100..2000 &&
                    intent.direction == null && intent.steps == null && intent.key == null
            }
            UiActionKind.SCROLL -> {
                intent.direction != null && intent.steps != null && intent.steps in 1..10 &&
                    intent.x == null && intent.y == null &&
                    intent.endX == null && intent.endY == null &&
                    intent.durationMs == null && intent.key == null
            }
            UiActionKind.KEY -> {
                intent.key != null &&
                    intent.x == null && intent.y == null &&
                    intent.endX == null && intent.endY == null &&
                    intent.durationMs == null && intent.steps == null &&
                    intent.direction == null
            }
        }
        if (!valid) return fail(UiActionPlanState.OUT_OF_BOUNDS)

        // Only bounded, strongly typed action fields are hashed. Nothing here
        // is a grant; real gestures are non-idempotent and never auto-replayed.
        val normalized = listOf(
            "v1", intent.kind.name, intent.windowHandle, intent.nodeHandle,
            intent.nodeEpoch, intent.rotation.toString(),
            intent.x.toString(), intent.y.toString(),
            intent.endX.toString(), intent.endY.toString(),
            intent.durationMs.toString(), intent.direction?.name.orEmpty(),
            intent.steps.toString(), intent.key?.name.orEmpty(),
        ).joinToString("|")
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(normalized.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        return UiActionPlanResult(
            UiActionPlanState.PLAN_ONLY, digest, true, false,
        )
    }

    private fun validCoord(x: Int?, y: Int?, env: UiActionEnvironment): Boolean =
        x != null && y != null && x in 0 until env.displayWidth &&
            y in 0 until env.displayHeight
}

/**
 * Pure cancellation semantics for testing only. A synthetic "dispatched"
 * marker is NOT a real Android input event. No UI mutation can be executed.
 */
class NativeUiActionLifecycle(private val plan: UiActionPlanResult) {
    private var cancellation: UiActionPlanState? = null
    private var fakeDispatched = false

    @Synchronized
    fun markFakeDispatchStarted() {
        if (cancellation == null && plan.state == UiActionPlanState.PLAN_ONLY) {
            fakeDispatched = true
        }
    }

    @Synchronized
    fun cancel(): UiActionPlanState {
        val previous = cancellation
        if (previous != null) return previous
        val value = if (fakeDispatched) {
            UiActionPlanState.UNCERTAIN
        } else {
            UiActionPlanState.CANCELLED
        }
        cancellation = value
        return value
    }

    fun realDispatchCount(): Int = 0
}

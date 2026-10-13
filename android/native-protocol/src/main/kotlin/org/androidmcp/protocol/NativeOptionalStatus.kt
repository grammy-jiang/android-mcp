package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N4.f app-scoped, single-shot optional capability status.
 * No location, microphone, contacts, notifications content, or nearby IDs.
 */
enum class OptionalCapability {
    BATTERY, DISPLAY, CONNECTIVITY, MOTION,
    LOCATION, MICROPHONE, CONTACTS, NOTIFICATION_CONTENT,
}
enum class OptionalReadiness {
    AVAILABLE, PARTIAL, PERMISSION_DENIED, UNSUPPORTED,
    UNAVAILABLE, DISABLED, THROTTLED, STOPPED,
}
enum class OptionalStopReason {
    FGS_STOP, ACTIVITY_DESTROYED, CLIENT_DISCONNECT, PROCESS_DEATH,
}

/** Every value is either ordinary own-app metadata or a coarse OS grant flag. */
data class OptionalStatusInput(
    val apiLevel: Int,
    val sampledElapsedMs: Long,
    val batteryPercent: Int?,
    val displayWidthPx: Int?,
    val displayHeightPx: Int?,
    val networkPermissionGranted: Boolean?,
    val networkValidated: Boolean?,
    val notificationsPermissionGranted: Boolean?,
    val motionSensorSupported: Boolean?,
    val foreground: Boolean = true,
)

data class OptionalStatusSnapshot(
    val schemaVersion: Int,
    val apiLevel: Int?,
    val sampledElapsedMs: Long?,
    val batteryPercent: Int?,
    val displayWidthPx: Int?,
    val displayHeightPx: Int?,
    val status: Map<OptionalCapability, OptionalReadiness>,
) {
    fun readiness(capability: OptionalCapability): OptionalReadiness =
        status[capability] ?: OptionalReadiness.UNAVAILABLE

    /** One small versioned result. No private sensor stream or OS exceptions. */
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("runtime", "android")
        put("api_level", apiLevel?.let(::JsonPrimitive) ?: JsonNull)
        put("sampled_elapsed_ms", sampledElapsedMs?.let(::JsonPrimitive) ?: JsonNull)
        put("battery_percent", batteryPercent?.let(::JsonPrimitive) ?: JsonNull)
        put("display_width_px", displayWidthPx?.let(::JsonPrimitive) ?: JsonNull)
        put("display_height_px", displayHeightPx?.let(::JsonPrimitive) ?: JsonNull)
        for (capability in OptionalCapability.entries) {
            put(capability.name.lowercase(), readiness(capability).name.lowercase())
        }
        put("synthetic_stream_only", true)
        put("live_subscription_enabled", false)
    }.toString()
}

/**
 * Readiness snapshots and an explicitly bounded synthetic-only sampling
 * fixture. This code cannot register real Android SensorManager listeners,
 * notifications, location updates or background telemetry collectors.
 */
class NativeOptionalStatusSession {
    private val fakeSamples = ArrayDeque<Long>()
    private var stopped = false

    @Synchronized
    fun snapshot(input: OptionalStatusInput): OptionalStatusSnapshot {
        if (stopped) return empty(input.apiLevel, OptionalReadiness.STOPPED)
        if (input.apiLevel !in 30..100) {
            return empty(null, OptionalReadiness.UNSUPPORTED)
        }
        if (!input.foreground) {
            return empty(input.apiLevel, OptionalReadiness.DISABLED)
        }
        val elapsed = input.sampledElapsedMs.takeIf { it >= 0 }
        val battery = input.batteryPercent?.takeIf { it in 0..100 }
        val dimsValid = input.displayWidthPx != null &&
            input.displayHeightPx != null &&
            input.displayWidthPx in 1..4096 &&
            input.displayHeightPx in 1..8192 &&
            input.displayWidthPx.toLong() * input.displayHeightPx <= 16_777_216L
        val width = input.displayWidthPx.takeIf { dimsValid }
        val height = input.displayHeightPx.takeIf { dimsValid }
        val connectivity = if (input.networkPermissionGranted == true) {
            if (input.networkValidated != null) OptionalReadiness.AVAILABLE
            else OptionalReadiness.UNAVAILABLE
        } else OptionalReadiness.PERMISSION_DENIED
        val motion = if (input.motionSensorSupported == true) {
            // The model never grants a real motion listener or polling loop.
            OptionalReadiness.DISABLED
        } else OptionalReadiness.UNSUPPORTED
        return OptionalStatusSnapshot(
            schemaVersion = 1,
            apiLevel = input.apiLevel,
            sampledElapsedMs = elapsed,
            batteryPercent = battery,
            displayWidthPx = width,
            displayHeightPx = height,
            status = mapOf(
                OptionalCapability.BATTERY to if (battery != null) {
                    OptionalReadiness.AVAILABLE
                } else OptionalReadiness.UNAVAILABLE,
                OptionalCapability.DISPLAY to if (dimsValid) {
                    OptionalReadiness.AVAILABLE
                } else OptionalReadiness.UNAVAILABLE,
                OptionalCapability.CONNECTIVITY to connectivity,
                OptionalCapability.MOTION to motion,
                OptionalCapability.LOCATION to OptionalReadiness.PERMISSION_DENIED,
                OptionalCapability.MICROPHONE to OptionalReadiness.PERMISSION_DENIED,
                OptionalCapability.CONTACTS to OptionalReadiness.PERMISSION_DENIED,
                OptionalCapability.NOTIFICATION_CONTENT to OptionalReadiness.PERMISSION_DENIED,
            ),
        )
    }

    @Synchronized
    fun sampleSynthetic(input: OptionalStatusInput): OptionalReadiness {
        if (stopped) return OptionalReadiness.STOPPED
        if (input.apiLevel !in 30..100) return OptionalReadiness.UNSUPPORTED
        if (!input.foreground) return OptionalReadiness.DISABLED
        if (input.sampledElapsedMs < 0) return OptionalReadiness.UNAVAILABLE
        if (fakeSamples.size >= MAX_EVENTS) return OptionalReadiness.THROTTLED
        val previous = fakeSamples.lastOrNull()
        if (previous != null &&
            (input.sampledElapsedMs <= previous ||
                input.sampledElapsedMs - previous < MIN_INTERVAL_MS)
        ) return OptionalReadiness.THROTTLED
        fakeSamples.addLast(input.sampledElapsedMs)
        return OptionalReadiness.AVAILABLE
    }

    @Synchronized
    fun eventCount(): Int = fakeSamples.size

    @Suppress("UNUSED_PARAMETER")
    @Synchronized
    fun stop(reason: OptionalStopReason) {
        stopped = true
        fakeSamples.clear()
    }

    fun realSensorSubscriptionAllowed(): Boolean = false

    private fun empty(api: Int?, status: OptionalReadiness) = OptionalStatusSnapshot(
        schemaVersion = 1,
        apiLevel = api,
        sampledElapsedMs = null,
        batteryPercent = null,
        displayWidthPx = null,
        displayHeightPx = null,
        status = OptionalCapability.entries.associateWith { status },
    )

    companion object {
        private const val MAX_EVENTS = 16
        private const val MIN_INTERVAL_MS = 1_000L
    }
}

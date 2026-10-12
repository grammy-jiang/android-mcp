package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Coarse own-process and listener health, with no PID, stacktrace, app account,
 * private path or permission tokens. Not a public MCP Tool or authentication.
 */
enum class NativeAppMode { ACTIVITY, FOREGROUND_SERVICE }
enum class NativeAppPhase { STOPPED, STARTING, RUNNING, STOPPING, FAILED_CLOSED, UNSUPPORTED }
enum class NativeStopCause { NONE, USER, NOTIFICATION, PROCESS_DEATH, FAILED_START, UNKNOWN }
enum class NativeHealthError {
    NONE, PORT_BUSY, PERMISSION_DENIED, UNVERIFIED_SHUTDOWN, START_TIMEOUT, INTERNAL, UNKNOWN
}

data class NativeAppHealthInput(
    val apiLevel: Int,
    val mode: NativeAppMode,
    val ownerPhase: NativeAppPhase,
    val listenerReady: Boolean,
    val foregroundNotificationPresent: Boolean,
    val processAlive: Boolean,
    val elapsedRealtimeMs: Long,
    val startedElapsedMs: Long?,
    val stopCause: NativeStopCause = NativeStopCause.NONE,
    val error: NativeHealthError = NativeHealthError.NONE,
)

class NativeAppHealth internal constructor(
    val schemaVersion: Int,
    val mode: NativeAppMode,
    val phase: NativeAppPhase,
    val uptimeMs: Long?,
    val endpointReady: Boolean,
    val stopCause: NativeStopCause,
    val error: NativeHealthError,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("mode", mode.name.lowercase())
        put("phase", phase.name.lowercase())
        put("uptime_ms", uptimeMs?.let(::JsonPrimitive) ?: JsonNull)
        put("endpoint_ready", endpointReady)
        put("stop_cause", stopCause.name.lowercase())
        put("error", error.name.lowercase())
    }.toString()
}

/**
 * A reported RUNNING state must have direct owner evidence of a listening
 * endpoint and, in FGS mode, a promoted ongoing foreground notification.
 *
 * Stale generations or a process-death signal can never claim readiness.
 * Uptime is process-monotonic and is not persisted or inferred from walltime.
 */
object NativeAppHealthSnapshots {
    private const val MIN_FGS_API = 34

    fun evaluate(input: NativeAppHealthInput): NativeAppHealth {
        val unsupported = input.apiLevel < 30 ||
            input.mode == NativeAppMode.FOREGROUND_SERVICE && input.apiLevel < MIN_FGS_API
        val dead = !input.processAlive
        val failure = input.error != NativeHealthError.NONE ||
            input.ownerPhase == NativeAppPhase.FAILED_CLOSED ||
            (input.ownerPhase == NativeAppPhase.RUNNING &&
                (!input.listenerReady ||
                    input.mode == NativeAppMode.FOREGROUND_SERVICE &&
                    !input.foregroundNotificationPresent))
        val phase = when {
            unsupported -> NativeAppPhase.UNSUPPORTED
            dead -> NativeAppPhase.STOPPED
            failure -> NativeAppPhase.FAILED_CLOSED
            else -> input.ownerPhase
        }
        val ready = phase == NativeAppPhase.RUNNING &&
            input.listenerReady &&
            (input.mode == NativeAppMode.ACTIVITY || input.foregroundNotificationPresent)
        val elapsed = input.elapsedRealtimeMs
        val started = input.startedElapsedMs
        val uptime = if (ready && started != null && started >= 0 &&
            elapsed >= started && elapsed - started <= 365L * 24 * 60 * 60 * 1000
        ) elapsed - started else null
        val error = if (failure && input.error == NativeHealthError.NONE) {
            NativeHealthError.UNKNOWN
        } else input.error
        val cause = if (dead && !unsupported) NativeStopCause.PROCESS_DEATH
        else input.stopCause
        return NativeAppHealth(
            schemaVersion = 1,
            mode = input.mode,
            phase = phase,
            uptimeMs = uptime,
            endpointReady = ready,
            stopCause = cause,
            error = error,
        )
    }
}

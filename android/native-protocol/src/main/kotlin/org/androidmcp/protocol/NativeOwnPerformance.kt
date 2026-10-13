package org.androidmcp.protocol

import java.util.UUID
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N5.b: own-process-only, synthetic-tested read-only performance model.
 * Not a systemwide profiler, root command, Perfetto trace or MCP Tool.
 */
enum class OwnPerformanceStatus {
    AVAILABLE, PARTIAL, DENIED, UNSUPPORTED, UNAVAILABLE, THROTTLED, STOPPED,
}
enum class OwnPerformanceStop {
    FGS_STOP, APP_SLEEP, PROCESS_DEATH, CLIENT_DISCONNECT,
}
data class OwnPerformanceInput(
    val apiLevel: Int,
    val epoch: String,
    val sampledElapsedMs: Long,
    val ownProcessCpuMs: Long?,
    val ownJavaHeapUsedBytes: Long?,
    val ownNativeHeapUsedBytes: Long?,
    val eventLatencyMs: Long?,
    val processAlive: Boolean,
    val appForeground: Boolean,
    val requestGlobalProfile: Boolean = false,
    val requestHighRateStream: Boolean = false,
)

data class OwnPerformanceResult(
    val status: OwnPerformanceStatus,
    val apiLevel: Int?,
    val sampledElapsedMs: Long?,
    val ownProcessCpuMs: Long?,
    val ownJavaHeapUsedBytes: Long?,
    val ownNativeHeapUsedBytes: Long?,
    val eventLatencyMs: Long?,
) {
    /** Never includes a PID, private stack, process name, or other-app data. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("runtime", "android")
        put("status", status.name.lowercase())
        put("api_level", apiLevel?.let(::JsonPrimitive) ?: JsonNull)
        put("sampled_elapsed_ms", sampledElapsedMs?.let(::JsonPrimitive) ?: JsonNull)
        put("own_cpu_time_ms", ownProcessCpuMs?.let(::JsonPrimitive) ?: JsonNull)
        put("own_java_heap_bytes", ownJavaHeapUsedBytes?.let(::JsonPrimitive) ?: JsonNull)
        put("own_native_heap_bytes", ownNativeHeapUsedBytes?.let(::JsonPrimitive) ?: JsonNull)
        put("own_event_latency_ms", eventLatencyMs?.let(::JsonPrimitive) ?: JsonNull)
        put("real_background_collection", false)
    }.toString()
}

/**
 * Finite in-memory synthetic history: 16 samples, at least 1 second apart.
 * All Stop/exit events invalidate the session. No Android sampling listener,
 * background scheduler, trace collection, OS event registration or restart.
 */
class NativeOwnPerformanceSession {
    val epoch: String = UUID.randomUUID().toString()
    private val observedAt = ArrayDeque<Long>()
    private var lastCpuMs: Long? = null
    private var stopped = false

    @Synchronized
    fun sample(input: OwnPerformanceInput): OwnPerformanceResult {
        fun empty(state: OwnPerformanceStatus) = OwnPerformanceResult(
            state, null, null, null, null, null, null,
        )
        if (stopped || !input.processAlive) {
            stopped = true
            observedAt.clear()
            lastCpuMs = null
            return empty(OwnPerformanceStatus.STOPPED)
        }
        if (input.apiLevel !in 30..100) return empty(OwnPerformanceStatus.UNSUPPORTED)
        if (input.epoch != epoch || input.requestGlobalProfile) {
            return empty(OwnPerformanceStatus.DENIED)
        }
        if (!input.appForeground) {
            observedAt.clear()
            lastCpuMs = null
            return empty(OwnPerformanceStatus.UNAVAILABLE)
        }
        if (input.requestHighRateStream) return empty(OwnPerformanceStatus.THROTTLED)
        if (input.sampledElapsedMs !in 0..MAX_ELAPSED_MS) {
            return empty(OwnPerformanceStatus.UNAVAILABLE)
        }
        if (observedAt.size >= MAX_SAMPLES) return empty(OwnPerformanceStatus.THROTTLED)
        val previous = observedAt.lastOrNull()
        if (previous != null &&
            (input.sampledElapsedMs <= previous ||
                input.sampledElapsedMs - previous < MIN_SAMPLE_INTERVAL_MS)
        ) return empty(OwnPerformanceStatus.THROTTLED)

        val cpu = input.ownProcessCpuMs?.takeIf { it in 0..MAX_CPU_MS }
        // Process CPU time cannot decrease within one process epoch. A
        // backwards sample means stale/restarted owner or a broken OEM
        // counter, and invalidates the short sample history.
        if (cpu != null && lastCpuMs != null && cpu < lastCpuMs!!) {
            observedAt.clear()
            lastCpuMs = null
            return empty(OwnPerformanceStatus.UNAVAILABLE)
        }
        val java = input.ownJavaHeapUsedBytes?.takeIf { it in 0..MAX_HEAP_BYTES }
        val native = input.ownNativeHeapUsedBytes?.takeIf { it in 0..MAX_HEAP_BYTES }
        val latency = input.eventLatencyMs?.takeIf { it in 0..MAX_LATENCY_MS }
        val state = if (cpu != null && java != null && native != null && latency != null) {
            OwnPerformanceStatus.AVAILABLE
        } else OwnPerformanceStatus.PARTIAL
        observedAt.addLast(input.sampledElapsedMs)
        if (cpu != null) lastCpuMs = cpu
        return OwnPerformanceResult(
            state, input.apiLevel, input.sampledElapsedMs,
            cpu, java, native, latency,
        )
    }

    @Synchronized
    fun sampleCount(): Int = observedAt.size

    @Suppress("UNUSED_PARAMETER")
    @Synchronized
    fun stop(reason: OwnPerformanceStop) {
        stopped = true
        observedAt.clear()
        lastCpuMs = null
    }

    /** No system process profiling or background sensor loop is authorized. */
    fun globalProfilerAllowed(): Boolean = false
    fun liveBackgroundSamplingAllowed(): Boolean = false

    companion object {
        private const val MAX_SAMPLES = 16
        private const val MIN_SAMPLE_INTERVAL_MS = 1_000L
        private const val MAX_ELAPSED_MS = 7L * 24 * 60 * 60 * 1000
        private const val MAX_CPU_MS = 30L * 24 * 60 * 60 * 1000
        private const val MAX_HEAP_BYTES = 1L shl 44
        private const val MAX_LATENCY_MS = 60_000L
    }
}

package org.androidmcp.lifecycle

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Path
import java.util.UUID

/**
 * N3.c synthetic-only fixture. There is NO Android MediaProjection,
 * MediaCodec, Surface, MediaRecorder, screen source, or real video encoder.
 */
enum class SyntheticRecordingStatus {
    STARTED_SYNTHETIC, SIMULATED_ONLY, DENIED, AUTH_REQUIRED,
    CONSENT_REQUIRED, FGS_TYPE_REQUIRED, REPLAY_DENIED, STALE_DENIED,
    BACKGROUND_DENIED, BUSY, CANCELLED, TIMED_OUT, TOO_LARGE, PARTIAL,
    INVALID_STREAM, STOPPED, ERROR
}

enum class SyntheticRecordingStopEvent {
    USER_CANCELLED, PROJECTION_ON_STOP, FGS_STOP, PROCESS_DEATH, ACTIVITY_DESTROYED,
}

data class SyntheticRecordingRequest(
    val durationMs: Int,
    val widthPx: Int,
    val heightPx: Int,
    val frameRate: Int,
    val maxBytes: Int,
)

data class SyntheticRecordingPermit(
    val apiLevel: Int,
    val processEpoch: String,
    val nonce: String,
    val syntheticOnly: Boolean,
    val fakeCallerAuthenticated: Boolean,
    val fakeUiConsentGranted: Boolean,
    val callerForeground: Boolean,
    val mediaProjectionFgsTypeDeclared: Boolean,
)

data class SyntheticRecordingResult(
    val status: SyntheticRecordingStatus,
    val artifact: NativeArtifactReceipt? = null,
) {
    /** Not a public Tool result. Never includes fake encoded bytes or handle. */
    fun metadataJson(): String =
        "{\"schema_version\":1,\"status\":\"" + status.name.lowercase() +
            "\",\"synthetic_only\":true,\"recording_executed\":false}"
}

/**
 * One process-epoch-bound, bounded, synthetic recording.
 *
 * Only a fake caller fixture may feed encoded test chunks. No OS-consent
 * token, capture source, encoder, or Android component is accepted; production
 * recording is unconditionally disabled. It is impossible to start a second
 * fake recording within one instance, even after a failed attempt.
 */
class NativeSyntheticRecording(
    private val appPrivateRoot: Path,
    private val elapsedClockMs: () -> Long = { System.nanoTime() / 1_000_000 },
) : AutoCloseable {
    val processEpoch: String = UUID.randomUUID().toString()
    private var closed = false
    private var spent = false
    private var recording = false
    private var finalStatus: SyntheticRecordingStatus = SyntheticRecordingStatus.STOPPED
    private var nonce: String? = null
    private var startTimeMs = 0L
    private var requested: SyntheticRecordingRequest? = null
    private var ownerStore: NativeArtifactStore? = null
    private val chunks = ArrayList<ByteArray>()
    private var totalBytes = 0

    @Synchronized
    fun start(
        permit: SyntheticRecordingPermit,
        request: SyntheticRecordingRequest,
    ): SyntheticRecordingStatus {
        if (closed) return SyntheticRecordingStatus.STOPPED
        if (permit.processEpoch != processEpoch) return SyntheticRecordingStatus.STALE_DENIED
        if (recording) {
            return if (nonce == permit.nonce) SyntheticRecordingStatus.REPLAY_DENIED
            else SyntheticRecordingStatus.BUSY
        }
        if (spent) return SyntheticRecordingStatus.REPLAY_DENIED
        if (!permit.syntheticOnly || permit.apiLevel !in 30..100) {
            return SyntheticRecordingStatus.DENIED
        }
        if (!permit.fakeCallerAuthenticated) return SyntheticRecordingStatus.AUTH_REQUIRED
        if (!permit.fakeUiConsentGranted) return SyntheticRecordingStatus.CONSENT_REQUIRED
        if (permit.apiLevel >= 34 && !permit.mediaProjectionFgsTypeDeclared) {
            return SyntheticRecordingStatus.FGS_TYPE_REQUIRED
        }
        if (!permit.callerForeground) return SyntheticRecordingStatus.BACKGROUND_DENIED
        if (permit.nonce.length !in 1..128 ||
            permit.nonce.any { it.code !in 0x21..0x7e }
        ) return SyntheticRecordingStatus.DENIED
        if (request.durationMs !in 1..MAX_DURATION_MS ||
            request.widthPx !in 1..MAX_WIDTH ||
            request.heightPx !in 1..MAX_HEIGHT ||
            request.widthPx.toLong() * request.heightPx > MAX_PIXELS ||
            request.frameRate !in 1..MAX_FRAME_RATE ||
            request.maxBytes !in MIN_CAPTURE_BYTES..MAX_RECORDING_BYTES
        ) return SyntheticRecordingStatus.DENIED
        val started = elapsedClockMs()
        if (started < 0L || started > Long.MAX_VALUE - request.durationMs) {
            return SyntheticRecordingStatus.DENIED
        }

        // This consumes the fake one-use session, even if the private file
        // lock fails. A failed process owner may not retry its fake grant.
        spent = true
        try {
            ownerStore = NativeArtifactStore(
                appPrivateRoot, ttlMs = PRIVATE_TTL_MS,
                maxArtifactBytes = request.maxBytes,
                maxTotalBytes = request.maxBytes.toLong(),
                maxEntries = 1,
            )
        } catch (_: Exception) {
            closed = true
            finalStatus = SyntheticRecordingStatus.ERROR
            return finalStatus
        }
        requested = request
        nonce = permit.nonce
        startTimeMs = started
        recording = true
        finalStatus = SyntheticRecordingStatus.STARTED_SYNTHETIC
        return finalStatus
    }

    @Synchronized
    fun appendChunk(data: ByteArray, droppedFrames: Int = 0): SyntheticRecordingStatus {
        if (!recording || closed) return SyntheticRecordingStatus.STOPPED
        val request = requested ?: return terminate(SyntheticRecordingStatus.ERROR)
        if (isPastDeadline(request)) return terminate(SyntheticRecordingStatus.TIMED_OUT)
        if (droppedFrames != 0) return terminate(SyntheticRecordingStatus.PARTIAL)
        if (data.isEmpty() || data.size > MAX_CHUNK_BYTES ||
            data.size > request.maxBytes - totalBytes
        ) return terminate(SyntheticRecordingStatus.TOO_LARGE)
        // Copy attacker-controlled fake bytes into private bounded memory.
        chunks.add(data.copyOf())
        totalBytes += data.size
        return SyntheticRecordingStatus.STARTED_SYNTHETIC
    }

    @Synchronized
    fun finish(): SyntheticRecordingResult {
        if (!recording || closed) return SyntheticRecordingResult(finalStatus)
        val request = requested ?: return SyntheticRecordingResult(
            terminate(SyntheticRecordingStatus.ERROR),
        )
        if (isPastDeadline(request)) {
            return SyntheticRecordingResult(terminate(SyntheticRecordingStatus.TIMED_OUT))
        }
        if (totalBytes !in MIN_CAPTURE_BYTES..request.maxBytes) {
            return SyntheticRecordingResult(terminate(SyntheticRecordingStatus.INVALID_STREAM))
        }
        val bytes = ByteArray(totalBytes)
        var offset = 0
        for (chunk in chunks) {
            chunk.copyInto(bytes, offset)
            offset += chunk.size
        }
        try {
            // Strict toy MP4 ftyp header only. No claim that these bytes are
            // an Android-encoded or independently playable actual video.
            if (!isValidFakeFtyp(bytes)) {
                return SyntheticRecordingResult(terminate(SyntheticRecordingStatus.INVALID_STREAM))
            }
            val privateOwner = ownerStore
                ?: return SyntheticRecordingResult(terminate(SyntheticRecordingStatus.ERROR))
            val receipt = privateOwner.create(bytes, "video/mp4")
            recording = false
            finalStatus = SyntheticRecordingStatus.SIMULATED_ONLY
            clearChunks()
            return SyntheticRecordingResult(SyntheticRecordingStatus.SIMULATED_ONLY, receipt)
        } catch (_: Exception) {
            return SyntheticRecordingResult(terminate(SyntheticRecordingStatus.ERROR))
        } finally {
            bytes.fill(0)
        }
    }

    @Synchronized
    fun failCodec(): SyntheticRecordingStatus = if (recording && !closed) {
        terminate(SyntheticRecordingStatus.ERROR)
    } else SyntheticRecordingStatus.STOPPED

    /** User Stop, MediaProjection.onStop and FGS death all purge and revoke. */
    @Suppress("UNUSED_PARAMETER")
    @Synchronized
    fun cancel(event: SyntheticRecordingStopEvent) {
        if (closed) return
        terminate(SyntheticRecordingStatus.CANCELLED)
    }

    @Synchronized
    fun isRecording(): Boolean = recording && !closed

    /** Every path, including fake success, refuses real device recording. */
    fun realRecordingAllowed(): Boolean = false

    private fun isPastDeadline(request: SyntheticRecordingRequest): Boolean {
        val current = elapsedClockMs()
        // The start-time preflight proved the upper bound cannot overflow.
        // A backwards or forged clock sample is never accepted as elapsed
        // time through signed Long subtraction wraparound.
        return current < startTimeMs ||
            current > startTimeMs + request.durationMs.toLong()
    }

    private fun isValidFakeFtyp(payload: ByteArray): Boolean {
        if (payload.size < MIN_CAPTURE_BYTES) return false
        val header = ByteBuffer.wrap(payload).order(ByteOrder.BIG_ENDIAN)
        val boxSize = header.getInt(0)
        if (boxSize !in 16..payload.size) return false
        return payload[4] == 'f'.code.toByte() &&
            payload[5] == 't'.code.toByte() &&
            payload[6] == 'y'.code.toByte() &&
            payload[7] == 'p'.code.toByte()
    }

    private fun clearChunks() {
        for (chunk in chunks) chunk.fill(0)
        chunks.clear()
        totalBytes = 0
    }

    private fun releaseStore() {
        try {
            ownerStore?.close()
        } catch (_: Exception) {
            // Fixed terminal status remains, no private exception exposed.
        } finally {
            ownerStore = null
        }
    }

    private fun terminate(status: SyntheticRecordingStatus): SyntheticRecordingStatus {
        finalStatus = status
        recording = false
        clearChunks()
        releaseStore()
        return status
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        recording = false
        clearChunks()
        releaseStore()
    }

    companion object {
        private const val MAX_DURATION_MS = 30_000
        private const val MAX_WIDTH = 1920
        private const val MAX_HEIGHT = 1080
        private const val MAX_PIXELS = 2_073_600L
        private const val MAX_FRAME_RATE = 30
        private const val MIN_CAPTURE_BYTES = 16
        private const val MAX_CHUNK_BYTES = 256 * 1024
        private const val MAX_RECORDING_BYTES = 8 * 1024 * 1024
        private const val PRIVATE_TTL_MS = 60_000L
    }
}

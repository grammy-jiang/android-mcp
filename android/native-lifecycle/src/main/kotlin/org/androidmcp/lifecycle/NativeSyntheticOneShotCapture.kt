package org.androidmcp.lifecycle

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.CRC32
import java.nio.file.Path
import java.util.UUID

/**
 * N3.b test-only frame contract. This class DOES NOT open MediaProjection,
 * ImageReader, VirtualDisplay, camera, SAF, or any Android screen source.
 *
 * An inert JVM synthetic fixture may write only caller-provided fake PNG
 * bytes to the N0.e app-private artifact store. It cannot perform live capture.
 */
enum class SyntheticCaptureStatus {
    SIMULATED_ONLY, DENIED, AUTH_REQUIRED, CONSENT_REQUIRED, FGS_TYPE_REQUIRED,
    LOCKED, SECURE_WINDOW, TOO_LARGE, INVALID_FRAME, TIMED_OUT,
    REPLAY_DENIED, STALE_DENIED, STOPPED, ERROR
}

data class SyntheticFrame(
    val widthPx: Int,
    val heightPx: Int,
    val mimeType: String,
    val bytes: ByteArray,
)

/**
 * Unit-test-controlled input, never populated from MCP, Intent extras, HTTP
 * headers or an actual Android MediaProjection token. No live grant exists.
 */
data class SyntheticCaptureContext(
    val apiLevel: Int,
    val processEpoch: String,
    val nonce: String,
    val syntheticOnly: Boolean,
    val fakeCallerAuthenticated: Boolean,
    val fakeUiConsentGranted: Boolean,
    val callerForeground: Boolean,
    val mediaProjectionFgsTypeDeclared: Boolean,
    val screenLocked: Boolean = false,
    val secureWindow: Boolean = false,
    val elapsedTimeMs: Long = 20,
)

data class SyntheticCaptureResult(
    val status: SyntheticCaptureStatus,
    val artifact: NativeArtifactReceipt?,
) {
    /** This is NOT a public Tool payload and deliberately omits artifact bytes. */
    fun publicMetadataJson(): String =
        "{\"schema_version\":1,\"status\":\"" + status.name.lowercase() +
            "\",\"synthetic_only\":true,\"capture_executed\":false}"
}

/**
 * Per-process one-shot fixture. No executor, background handler or MediaProjection
 * attachment. Close is equivalent to synthetic FGS Stop or projection onStop:
 * purge all private artifacts and invalidate this entire one-shot session.
 */
class NativeSyntheticOneShotCapture(
    private val appPrivateRoot: Path,
) : AutoCloseable {
    val processEpoch: String = UUID.randomUUID().toString()
    private var closed = false
    private var spent = false
    private var artifacts: NativeArtifactStore? = null

    @Synchronized
    fun trySyntheticFrame(
        context: SyntheticCaptureContext,
        frame: SyntheticFrame,
    ): SyntheticCaptureResult {
        fun fail(status: SyntheticCaptureStatus) = SyntheticCaptureResult(status, null)
        if (closed) return fail(SyntheticCaptureStatus.STOPPED)
        if (context.processEpoch != processEpoch) return fail(SyntheticCaptureStatus.STALE_DENIED)
        if (!context.syntheticOnly || context.apiLevel !in 30..100) {
            return fail(SyntheticCaptureStatus.DENIED)
        }
        if (!context.fakeCallerAuthenticated) return fail(SyntheticCaptureStatus.AUTH_REQUIRED)
        if (!context.fakeUiConsentGranted) return fail(SyntheticCaptureStatus.CONSENT_REQUIRED)
        if (context.apiLevel >= 34 && !context.mediaProjectionFgsTypeDeclared) {
            return fail(SyntheticCaptureStatus.FGS_TYPE_REQUIRED)
        }
        if (!context.callerForeground) return fail(SyntheticCaptureStatus.DENIED)
        if (context.screenLocked) return fail(SyntheticCaptureStatus.LOCKED)
        if (context.secureWindow) return fail(SyntheticCaptureStatus.SECURE_WINDOW)
        if (spent) return fail(SyntheticCaptureStatus.REPLAY_DENIED)
        if (context.nonce.length !in 1..128 ||
            context.nonce.any { it.code !in 0x21..0x7E }
        ) return fail(SyntheticCaptureStatus.DENIED)
        if (context.elapsedTimeMs !in 0..MAX_CAPTURE_MS) {
            return fail(SyntheticCaptureStatus.TIMED_OUT)
        }
        if (frame.bytes.size > MAX_FRAME_BYTES) return fail(SyntheticCaptureStatus.TOO_LARGE)
        // Snapshot before validation: a caller may mutate its original buffer
        // concurrently, but the validated bytes and published bytes must be
        // identical. Only this private snapshot is ever written to disk.
        val copy = frame.bytes.copyOf()
        try {
            if (frame.mimeType != "image/png" ||
                !validSyntheticPng(frame.copy(bytes = copy))
            ) return fail(SyntheticCaptureStatus.INVALID_FRAME)

            // One consent fixture can be consumed at most once, including
            // I/O failure. Never retry a projection-like nonce after partial
            // filesystem publication.
            spent = true
            try {
                val owned = NativeArtifactStore(
                    appPrivateRoot,
                    maxArtifactBytes = MAX_FRAME_BYTES,
                    maxTotalBytes = MAX_FRAME_BYTES.toLong(),
                    maxEntries = 1,
                    ttlMs = 60_000,
                )
                artifacts = owned
                val receipt = owned.create(copy, "image/png")
                return SyntheticCaptureResult(SyntheticCaptureStatus.SIMULATED_ONLY, receipt)
            } catch (_: Exception) {
                // No error message containing private file paths is exposed.
                try { close() } catch (_: Exception) { /* fail closed */ }
                return fail(SyntheticCaptureStatus.ERROR)
            }
        } finally {
            // Wipe only the private snapshot, never caller-owned fixture data.
            copy.fill(0)
        }
    }

    private fun validSyntheticPng(frame: SyntheticFrame): Boolean {
        // The synthetic fixture accepts a deliberately narrow, lossless PNG
        // subset: one IHDR, one or more IDATs, and a final IEND. All chunks
        // must be within the byte budget and pass CRC32. There is no pixel
        // decoding, real screen access, or acceptance of embedded metadata.
        if (frame.widthPx !in 1..MAX_DIMENSION ||
            frame.heightPx !in 1..MAX_DIMENSION ||
            frame.widthPx.toLong() * frame.heightPx > MAX_PIXELS ||
            frame.bytes.size !in 57..MAX_FRAME_BYTES
        ) return false
        val bytes = frame.bytes
        if (!bytes.copyOfRange(0, PNG_MAGIC.size).contentEquals(PNG_MAGIC)) return false
        val header = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)
        var offset = PNG_MAGIC.size
        var sawIHDR = false
        var sawIDAT = false
        var sawIEND = false
        while (offset + 12 <= bytes.size) {
            val length = header.getInt(offset)
            if (length < 0 || offset.toLong() + length + 12L > bytes.size.toLong()) {
                return false
            }
            val type = bytes.copyOfRange(offset + 4, offset + 8)
            val crc = CRC32()
            crc.update(bytes, offset + 4, length + 4)
            if (crc.value.toInt() != header.getInt(offset + 8 + length)) return false
            when {
                type.contentEquals(IHDR) -> {
                    if (sawIHDR || sawIDAT || length != 13 || offset != 8) return false
                    if (header.getInt(offset + 8) != frame.widthPx ||
                        header.getInt(offset + 12) != frame.heightPx ||
                        bytes[offset + 16] != 8.toByte() ||
                        bytes[offset + 17] != 6.toByte() ||
                        bytes[offset + 18] != 0.toByte() ||
                        bytes[offset + 19] != 0.toByte() ||
                        bytes[offset + 20] != 0.toByte()
                    ) return false
                    sawIHDR = true
                }
                type.contentEquals(IDAT) -> {
                    if (!sawIHDR || sawIEND || length == 0) return false
                    sawIDAT = true
                }
                type.contentEquals(IEND) -> {
                    if (!sawIHDR || !sawIDAT || sawIEND || length != 0) return false
                    sawIEND = true
                }
                else -> return false // No ancillary chunks or hidden metadata.
            }
            offset += length + 12
            if (sawIEND) return offset == bytes.size
        }
        return false
    }

    /** There is intentionally NO route to capture a real Android frame. */
    fun captureRealIsAllowed(): Boolean = false

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        try {
            artifacts?.close()
        } finally {
            artifacts = null
        }
    }

    companion object {
        private const val MAX_DIMENSION = 4096
        private const val MAX_PIXELS = 4_194_304L
        private const val MAX_FRAME_BYTES = 8 * 1024 * 1024
        private const val MAX_CAPTURE_MS = 3_000L
        private val PNG_MAGIC = byteArrayOf(
            -119, 80, 78, 71, 13, 10, 26, 10,
        )
        private val IHDR = byteArrayOf(73, 72, 68, 82)
        private val IDAT = byteArrayOf(73, 68, 65, 84)
        private val IEND = byteArrayOf(73, 69, 78, 68)
    }
}

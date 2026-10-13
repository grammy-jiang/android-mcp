package org.androidmcp.lifecycle

import java.nio.file.Path
import java.util.UUID

/**
 * N5.a synthetic, self-owned diagnostics only. No global Logcat, tombstones,
 * stack trace collector, ActivityManager, other-process access, or public MCP.
 */
enum class NativeCrashCode { OWN_EXCEPTION, OWN_ANR, OWN_FGS_FAILURE }
enum class NativeCrashState {
    RECORDED, DENIED, INCOMPLETE, EXPIRED, STOPPED, DUPLICATE, BUSY, UNSUPPORTED
}

/**
 * A synthetic exception message is accepted but deliberately ignored and
 * never copied to the report. Do not accidentally leak it via Kotlin data
 * class toString() in any diagnostics.
 */
data class NativeCrashInput(
    val packageName: String,
    val apiLevel: Int,
    val processEpoch: String,
    val eventNonce: String,
    val appVersion: String,
    val uptimeMs: Long,
    val code: NativeCrashCode,
    val privateExceptionMessage: String?,
) {
    override fun toString(): String = "NativeCrashInput([REDACTED])"
}

/** Internal private artifact receipt never appears in public-style metadata. */
data class NativeCrashResult(
    val state: NativeCrashState,
    val artifact: NativeArtifactReceipt? = null,
) {
    fun publicMetadataJson(): String =
        "{\"schema_version\":1,\"status\":\"" + state.name.lowercase() +
            "\",\"read_only\":true,\"synthetic_only\":true," +
            "\"live_diagnostics_enabled\":false}"

    override fun toString(): String =
        "NativeCrashResult(status=" + state.name + ", artifact=[REDACTED])"
}

/**
 * One bounded owner of synthetic own-process crash/ANR diagnostics. A record
 * contains only fixed event code and public-safe app version + uptime.
 *
 * It is not a JVM uncaught exception handler and never registers callbacks
 * or reads Android platform diagnostics. The Android runtime boundary
 * remains denied until an explicit reviewed owner is implemented.
 */
class NativeOwnCrashDiagnostics(
    private val privateRoot: Path,
    private val clock: () -> Long,
    private val storageFactory: ((Path, () -> Long) -> NativeArtifactStore)? = null,
) : AutoCloseable {
    val processEpoch = UUID.randomUUID().toString()
    private var closed = false
    private var faulted = false
    private val nonces = HashSet<String>()
    private var store: NativeArtifactStore? = null

    init {
        // Ownership must be established on construction, not lazily on the
        // first new report: the first reader after a crash must discard
        // stale previous-process report files before returning any status.
        try {
            store = storageFactory?.invoke(privateRoot, clock)
                ?: NativeArtifactStore(
                    privateRoot,
                    clock = clock,
                    ttlMs = RETENTION_MS,
                    maxArtifactBytes = MAX_REPORT_BYTES,
                    maxTotalBytes = MAX_REPORT_BYTES.toLong() * MAX_RECORDS,
                    maxEntries = MAX_RECORDS,
                )
        } catch (_: Exception) {
            faulted = true
        }
    }

    @Synchronized
    fun record(input: NativeCrashInput): NativeCrashResult {
        fun deny(code: NativeCrashState): NativeCrashResult =
            NativeCrashResult(code)
        if (closed) return deny(NativeCrashState.STOPPED)
        if (faulted) return deny(NativeCrashState.INCOMPLETE)
        if (input.apiLevel !in 30..100) return deny(NativeCrashState.UNSUPPORTED)
        if (input.processEpoch != processEpoch ||
            input.packageName != OWN_PACKAGE ||
            !NONCE.matches(input.eventNonce) ||
            !VERSION.matches(input.appVersion) ||
            !input.appVersion.first().isDigit() ||
            VERSION_FORBIDDEN.any { input.appVersion.contains(it, ignoreCase = true) } ||
            input.uptimeMs !in 0..MAX_UPTIME_MS
        ) return deny(NativeCrashState.DENIED)
        if (input.eventNonce in nonces) return deny(NativeCrashState.DUPLICATE)
        if (nonces.size >= MAX_RECORDS) return deny(NativeCrashState.BUSY)

        // Never put input.privateExceptionMessage, Throwable.toString(),
        // stacktrace, process IDs, URI or private path into this payload.
        val fixedJson =
            "{\"schema_version\":1,\"runtime\":\"android\",\"app_version\":\"" +
                input.appVersion + "\",\"uptime_ms\":" + input.uptimeMs +
                ",\"code\":\"" + input.code.name.lowercase() +
                "\",\"synthetic_only\":true}"
        val bytes = fixedJson.toByteArray(Charsets.UTF_8)
        if (bytes.size !in 1..MAX_REPORT_BYTES) {
            bytes.fill(0)
            return deny(NativeCrashState.DENIED)
        }
        try {
            val privateOwner = store ?: return deny(NativeCrashState.INCOMPLETE)
            privateOwner.purgeExpired()
            val receipt = privateOwner.create(bytes, "application/json")
            nonces.add(input.eventNonce)
            return NativeCrashResult(NativeCrashState.RECORDED, receipt)
        } catch (_: Exception) {
            // Failed/crashed owner must not leave a success receipt or a
            // usable stale reference. N0.e cleans unfinished private files.
            faulted = true
            try { store?.close() } catch (_: Exception) { /* deny */ }
            store = null
            return deny(NativeCrashState.INCOMPLETE)
        } finally {
            bytes.fill(0)
        }
    }

    @Synchronized
    fun readPrivate(handle: String): ByteArray? {
        if (closed || faulted || !HANDLE.matches(handle)) return null
        return try {
            store?.read(handle)
        } catch (_: Exception) {
            null
        }
    }

    @Synchronized
    fun activeCount(): Int {
        if (closed || faulted) return 0
        return try {
            store?.purgeExpired()
            store?.activeCount() ?: 0
        } catch (_: Exception) {
            0
        }
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        nonces.clear()
        try { store?.close() } catch (_: Exception) { /* deny */ }
        store = null
    }

    companion object {
        private const val OWN_PACKAGE = "org.androidmcp.nativeapp"
        private const val MAX_RECORDS = 4
        private const val MAX_REPORT_BYTES = 16 * 1024
        private const val RETENTION_MS = 120_000L
        private const val MAX_UPTIME_MS = 7L * 24 * 60 * 60 * 1000
        private val NONCE = Regex("[A-Za-z0-9_-]{1,128}")
        private val VERSION = Regex("[A-Za-z0-9._+-]{1,32}")
        private val VERSION_FORBIDDEN = listOf(
            "secret", "token", "password", "credential", "account", "private",
        )
        private val HANDLE = Regex("[A-Za-z0-9_-]{32}")
    }
}

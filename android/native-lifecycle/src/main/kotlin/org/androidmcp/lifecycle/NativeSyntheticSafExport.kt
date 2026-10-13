package org.androidmcp.lifecycle

import java.io.IOException
import java.io.InputStream
import java.nio.file.Path
import java.security.MessageDigest
import java.util.concurrent.Callable
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.androidmcp.protocol.NativeSafGrantPolicy
import org.androidmcp.protocol.SafAccessMode
import org.androidmcp.protocol.SafGrantStatus

/**
 * N4.d: strictly synthetic, never opens Android ContentResolver.
 * A simulated grant permits only one exact fake document URI and READ scope.
 */
enum class SafExportStatus {
    SIMULATED_ONLY, DENIED, CANCELLED, REVOKED, EXPIRED, STALE, OVERSIZE,
    BROKEN_PROVIDER, WRONG_PROVIDER, BUSY, UNCERTAIN, IO_FAILURE, STOPPED,
}

data class SyntheticDocument(
    val uri: String,
    val authority: String,
    val providerProcessId: String,
    val mimeType: String,
    val declaredLength: Long?,
    val stream: InputStream,
) {
    override fun toString(): String = "SyntheticDocument([REDACTED])"
}
fun interface SyntheticDocumentProvider {
    fun openSelected(uri: String): SyntheticDocument
}
data class SafExportRequest(
    val grantHandle: String,
    val selectedUri: String,
    val idempotencyKey: String,
) {
    override fun toString(): String = "SafExportRequest([REDACTED])"
}
data class SafExportResult(
    val status: SafExportStatus,
    val artifact: NativeArtifactReceipt? = null,
) {
    fun metadataJson(): String =
        "{\"schema_version\":1,\"status\":\"" + status.name.lowercase() +
            "\",\"synthetic_only\":true,\"real_io_allowed\":false}"
    override fun toString(): String =
        "SafExportResult(status=" + status.name + ", artifact=[REDACTED])"

}

/**
 * Process-local fake SAF exporter. Bounded worker reads synthetic streams;
 * only the caller thread commits an app-private artifact after verifying
 * deadline, cancellation and original N4.c URI-scope authorization.
 */
class NativeSyntheticSafExporter(
    private val privateRoot: Path,
    private val grants: NativeSafGrantPolicy,
    private val trustedAuthority: String,
    private val trustedProviderProcessId: String,
    private val clockElapsedMs: () -> Long,
) : AutoCloseable {
    private data class ReadOutcome(
        val status: SafExportStatus,
        val data: ByteArray? = null,
        val mime: String? = null,
    )
    private data class Memo(
        val grantHandle: String,
        val selectedUriHash: ByteArray,
        val receipt: NativeArtifactReceipt,
    )

    private val cancelled = AtomicBoolean(false)
    private val activeStream = AtomicReference<InputStream?>(null)
    private val task = AtomicReference<Future<ReadOutcome>?>(null)
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "native-saf-export-fixture").apply { isDaemon = true }
    }
    private val records = HashMap<String, Memo>()
    private var closed = false
    private var terminalError = false
    private var artifacts: NativeArtifactStore? = null

    @Synchronized
    fun export(
        request: SafExportRequest,
        provider: SyntheticDocumentProvider,
    ): SafExportResult {
        fun fail(value: SafExportStatus) = SafExportResult(value)
        if (closed) return fail(SafExportStatus.STOPPED)
        if (cancelled.get()) return fail(SafExportStatus.CANCELLED)
        if (terminalError) return fail(SafExportStatus.UNCERTAIN)
        if (!KEY.matches(request.idempotencyKey)) return fail(SafExportStatus.DENIED)

        when (grants.check(request.grantHandle, SafAccessMode.READ)) {
            SafGrantStatus.REVOKED -> return fail(SafExportStatus.REVOKED)
            SafGrantStatus.EXPIRED -> return fail(SafExportStatus.EXPIRED)
            SafGrantStatus.SIMULATED_ONLY -> Unit
            else -> return fail(SafExportStatus.DENIED)
        }
        if (!grants.matchesSelectedUri(
                request.grantHandle, request.selectedUri, SafAccessMode.READ,
            )
        ) return fail(SafExportStatus.DENIED)

        records[request.idempotencyKey]?.let { old ->
            return if (old.grantHandle == request.grantHandle &&
                MessageDigest.isEqual(
                    old.selectedUriHash, scopedUriHash(request.selectedUri),
                )
            ) SafExportResult(SafExportStatus.SIMULATED_ONLY, old.receipt)
            else fail(SafExportStatus.DENIED)
        }
        if (records.size >= MAX_DOCUMENTS) return fail(SafExportStatus.OVERSIZE)
        val startMs = clockElapsedMs()
        if (startMs < 0 || startMs > Long.MAX_VALUE - TIMEOUT_MS) {
            return fail(SafExportStatus.DENIED)
        }
        val future = executor.submit(Callable {
            readFakeProvider(provider, request.selectedUri, startMs)
        })
        task.set(future)
        val outcome = try {
            future.get(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        } catch (_: TimeoutException) {
            terminalError = true
            cancelled.set(true)
            future.cancel(true)
            closeActiveStream()
            return fail(SafExportStatus.UNCERTAIN)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            terminalError = true
            cancelled.set(true)
            future.cancel(true)
            closeActiveStream()
            return fail(SafExportStatus.UNCERTAIN)
        } catch (_: ExecutionException) {
            if (cancelled.get()) return fail(SafExportStatus.CANCELLED)
            terminalError = true
            return fail(SafExportStatus.BROKEN_PROVIDER)
        } catch (_: RuntimeException) {
            if (cancelled.get()) return fail(SafExportStatus.CANCELLED)
            terminalError = true
            return fail(SafExportStatus.BROKEN_PROVIDER)
        } finally {
            task.compareAndSet(future, null)
        }

        if (cancelled.get()) {
            outcome.data?.fill(0)
            return fail(SafExportStatus.CANCELLED)
        }
        if (clockElapsedMs() !in startMs..(startMs + TIMEOUT_MS)) {
            outcome.data?.fill(0)
            terminalError = true
            return fail(SafExportStatus.UNCERTAIN)
        }
        if (outcome.status != SafExportStatus.SIMULATED_ONLY ||
            outcome.data == null || outcome.mime == null
        ) {
            outcome.data?.fill(0)
            return fail(outcome.status)
        }
        // Revalidate the original exact user-selected grant AFTER provider
        // read and BEFORE artifact publication. A user revocation during
        // the fake provider operation must never publish a stale document.
        val newest = grants.check(request.grantHandle, SafAccessMode.READ)
        if (newest != SafGrantStatus.SIMULATED_ONLY ||
            !grants.matchesSelectedUri(
                request.grantHandle, request.selectedUri, SafAccessMode.READ,
            )
        ) {
            outcome.data.fill(0)
            return fail(
                when (newest) {
                    SafGrantStatus.REVOKED -> SafExportStatus.REVOKED
                    SafGrantStatus.EXPIRED -> SafExportStatus.EXPIRED
                    else -> SafExportStatus.DENIED
                },
            )
        }
        val bytes = outcome.data
        try {
            val store = artifacts ?: NativeArtifactStore(
                privateRoot, maxArtifactBytes = MAX_BYTES,
                maxTotalBytes = MAX_BYTES.toLong() * MAX_DOCUMENTS,
                maxEntries = MAX_DOCUMENTS, ttlMs = ARTIFACT_TTL_MS,
            ).also { artifacts = it }
            val receipt = store.create(bytes, outcome.mime)
            if (cancelled.get() ||
                grants.check(request.grantHandle, SafAccessMode.READ) !=
                    SafGrantStatus.SIMULATED_ONLY
            ) {
                store.remove(receipt.handle)
                return fail(
                    if (cancelled.get()) SafExportStatus.CANCELLED
                    else SafExportStatus.REVOKED,
                )
            }
            records[request.idempotencyKey] = Memo(
                request.grantHandle, scopedUriHash(request.selectedUri), receipt,
            )
            return SafExportResult(SafExportStatus.SIMULATED_ONLY, receipt)
        } catch (_: Exception) {
            terminalError = true
            try { artifacts?.close() } catch (_: Exception) { /* deny */ }
            artifacts = null
            records.clear()
            return fail(SafExportStatus.IO_FAILURE)
        } finally {
            bytes.fill(0)
        }
    }

    private fun scopedUriHash(uri: String): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(uri.toByteArray(Charsets.UTF_8))

    private fun readFakeProvider(
        provider: SyntheticDocumentProvider,
        uri: String,
        startMs: Long,
    ): ReadOutcome {
        val document = try {
            provider.openSelected(uri)
        } catch (_: Exception) {
            return ReadOutcome(SafExportStatus.BROKEN_PROVIDER)
        }
        activeStream.set(document.stream)
        return try {
            document.stream.use { source ->
                if (document.uri != uri ||
                    document.authority != trustedAuthority ||
                    document.providerProcessId != trustedProviderProcessId
                ) return ReadOutcome(SafExportStatus.WRONG_PROVIDER)
                if (!MIME.matches(document.mimeType)) {
                    return ReadOutcome(SafExportStatus.BROKEN_PROVIDER)
                }
                if (document.declaredLength != null &&
                    document.declaredLength !in 1L..MAX_BYTES.toLong()
                ) return ReadOutcome(SafExportStatus.OVERSIZE)
                // Keep exactly one fixed-size buffer so its contents can
                // be cleared. Do not retain a ByteArrayOutputStream backing
                // array containing another application's fake document.
                val buffer = ByteArray(BUFFER_SIZE)
                val accumulator = ByteArray(MAX_BYTES)
                var length = 0
                try {
                    while (true) {
                        if (cancelled.get() || Thread.currentThread().isInterrupted) {
                            return ReadOutcome(SafExportStatus.CANCELLED)
                        }
                        val current = clockElapsedMs()
                        if (current < startMs || current > startMs + TIMEOUT_MS) {
                            return ReadOutcome(SafExportStatus.UNCERTAIN)
                        }
                        val read = source.read(buffer)
                        if (read == -1) break
                        if (read == 0) continue
                        if (read > MAX_BYTES - length) {
                            return ReadOutcome(SafExportStatus.OVERSIZE)
                        }
                        buffer.copyInto(accumulator, length, 0, read)
                        length += read
                        buffer.fill(0)
                    }
                    if (length == 0 ||
                        document.declaredLength != null &&
                        length.toLong() != document.declaredLength
                    ) return ReadOutcome(SafExportStatus.BROKEN_PROVIDER)
                    ReadOutcome(
                        SafExportStatus.SIMULATED_ONLY,
                        accumulator.copyOf(length),
                        document.mimeType,
                    )
                } finally {
                    buffer.fill(0)
                    accumulator.fill(0)
                }
            }
        } catch (_: IOException) {
            ReadOutcome(SafExportStatus.BROKEN_PROVIDER)
        } catch (_: RuntimeException) {
            ReadOutcome(SafExportStatus.BROKEN_PROVIDER)
        } finally {
            activeStream.compareAndSet(document.stream, null)
        }
    }

    /** Outside export's lock so a blocked synthetic provider can be stopped. */
    fun cancel() {
        cancelled.set(true)
        task.get()?.cancel(true)
        closeActiveStream()
        synchronized(this) {
            try { artifacts?.close() } catch (_: Exception) { /* deny */ }
            artifacts = null
            records.clear()
        }
    }

    private fun closeActiveStream() {
        try {
            activeStream.getAndSet(null)?.close()
        } catch (_: Exception) {
            // Platform/provider cancellation is uncertain, never success.
        }
    }

    @Synchronized
    fun activeArtifacts(): Int = try {
        artifacts?.activeCount() ?: 0
    } catch (_: Exception) {
        0
    }

    fun realContentResolverAccessAllowed(): Boolean = false

    override fun close() {
        cancel()
        synchronized(this) { closed = true }
        executor.shutdownNow()
    }

    companion object {
        private const val MAX_BYTES = 1024 * 1024
        private const val MAX_DOCUMENTS = 4
        private const val BUFFER_SIZE = 8192
        private const val TIMEOUT_MS = 1_500L
        private const val ARTIFACT_TTL_MS = 60_000L
        private val MIME = Regex("[a-z0-9][a-z0-9.+_-]{0,63}/[a-z0-9][a-z0-9.+_-]{0,63}")
        private val KEY = Regex("[A-Za-z0-9_-]{1,64}")
    }
}

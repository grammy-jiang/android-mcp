package org.androidmcp.protocol

import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Pure request metadata from Ktor. Headers are untrusted: a caller on Android
 * loopback may be another app, not the user or a paired Host. No field in this
 * structure is an authentication proof.
 */
data class LocalHttpRequest(
    val method: String = "POST",
    val path: String = "/mcp",
    val host: String? = "127.0.0.1:38765",
    val origin: String? = null,
    val remoteHost: String = "127.0.0.1",
    val contentLength: String? = "100",
    val transferEncoding: String? = null,
    val headerCount: Int = 6,
    val headerBytes: Int = 256,
    val duplicateSecurityHeaders: Boolean = false,
)

data class GuardVerdict(
    val allowed: Boolean,
    val httpStatus: Int,
    val code: String,
) {
    companion object {
        val publicStatus = GuardVerdict(true, 200, "NATIVE_STATUS_ONLY")
        fun deny(status: Int, code: String) = GuardVerdict(false, status, code)
    }
}

/**
 * Fake-only N6 design input; it is intentionally never extracted from HTTP
 * headers, persisted, exposed over MCP or accepted as a live signed grant.
 */
data class SyntheticCallerApproval(
    val epoch: String,
    val nonce: String,
    val fakeSignatureAccepted: Boolean,
)

/** Releasing twice must not consume another request's slot. */
class GuardTicket(
    val verdict: GuardVerdict,
    private val release: () -> Unit = {},
) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    override fun close() {
        if (closed.compareAndSet(false, true)) release()
    }
}

/**
 * N0.b: deny hostile origins/hosts before dispatch, and never enable
 * sensitive Tools based on localhost IP, Origin or synthetic approval.
 *
 * This is not authentication or a distributed Host/Native lease. A future N6
 * pairing/security-reviewed transport is needed for sensitive capabilities.
 */
class NativeLocalCallerGuard(private val maxInFlight: Int = 32) {
    init {
        require(maxInFlight in 1..128)
    }

    val epoch: String = UUID.randomUUID().toString()
    private val active = AtomicInteger(0)
    private val seenSyntheticNonces = HashSet<String>()

    /** Public v1 status remains callable from a local non-browser SDK client. */
    fun evaluate(request: LocalHttpRequest): GuardVerdict {
        if (request.headerCount !in 0..48 || request.headerBytes !in 0..8192) {
            return GuardVerdict.deny(431, "NATIVE_HEADERS_TOO_LARGE")
        }
        if (request.duplicateSecurityHeaders) {
            return GuardVerdict.deny(400, "NATIVE_DUPLICATE_HEADER")
        }
        if (request.remoteHost !in setOf("127.0.0.1", "::1", "localhost")) {
            return GuardVerdict.deny(403, "NATIVE_NON_LOCAL_CALLER")
        }
        if (!localAuthority(request.host)) {
            return GuardVerdict.deny(403, "NATIVE_BAD_HOST")
        }
        if (request.origin != null && !localOrigin(request.origin)) {
            return GuardVerdict.deny(403, "NATIVE_BAD_ORIGIN")
        }
        if (request.method == "OPTIONS") {
            return GuardVerdict.deny(403, "NATIVE_PREFLIGHT_DENIED")
        }
        if (request.transferEncoding != null) {
            // Unknown-length/chunked requests cannot bypass size accounting.
            return GuardVerdict.deny(411, "NATIVE_LENGTH_REQUIRED")
        }
        if (request.path == "/mcp") {
            if (request.method !in setOf("GET", "POST", "DELETE")) {
                return GuardVerdict.deny(405, "NATIVE_METHOD_DENIED")
            }
        } else if (
            request.path.matches(Regex("/_native_internal/ready/[a-f0-9]{32}")) &&
            request.method == "GET"
        ) {
            // Readiness marker is not an authentication secret.
        } else {
            return GuardVerdict.deny(404, "NATIVE_UNKNOWN_PATH")
        }
        if (request.contentLength != null) {
            val raw = request.contentLength
            if (raw.length > 8 || raw.isEmpty() || raw.any { !it.isDigit() }) {
                return GuardVerdict.deny(400, "NATIVE_BAD_LENGTH")
            }
            val length = raw.toLongOrNull()
                ?: return GuardVerdict.deny(400, "NATIVE_BAD_LENGTH")
            if (length > MAX_BODY_BYTES) {
                return GuardVerdict.deny(413, "NATIVE_BODY_TOO_LARGE")
            }
        } else if (request.method == "POST") {
            return GuardVerdict.deny(411, "NATIVE_LENGTH_REQUIRED")
        }
        return GuardVerdict.publicStatus
    }

    /**
     * This fake recognition is purposefully inert; no amount of synthetic
     * proof authorizes capture, PackageManager, Accessibility or mutation.
     */
    @Synchronized
    fun recognizeSynthetic(
        request: LocalHttpRequest,
        approval: SyntheticCallerApproval,
    ): GuardVerdict {
        val transport = evaluate(request)
        if (!transport.allowed) return transport
        if (request.origin == null) {
            return GuardVerdict.deny(403, "NATIVE_SYNTHETIC_ORIGIN_REQUIRED")
        }
        if (approval.epoch != epoch) {
            return GuardVerdict.deny(403, "NATIVE_STALE")
        }
        if (!approval.fakeSignatureAccepted) {
            return GuardVerdict.deny(403, "NATIVE_BAD_SYNTHETIC_PROOF")
        }
        if (approval.nonce.length !in 1..128 || approval.nonce.any { it.code < 0x20 }) {
            return GuardVerdict.deny(400, "NATIVE_BAD_NONCE")
        }
        if (approval.nonce in seenSyntheticNonces) {
            return GuardVerdict.deny(409, "NATIVE_REPLAY")
        }
        if (seenSyntheticNonces.size >= MAX_SYNTHETIC_NONCES) {
            return GuardVerdict.deny(429, "NATIVE_FAKE_REPLAY_CACHE_FULL")
        }
        seenSyntheticNonces.add(approval.nonce)
        return GuardVerdict(true, 200, "RECOGNIZED_INERT")
    }

    @Suppress("UNUSED_PARAMETER")
    fun authorizeSensitive(
        request: LocalHttpRequest,
        toolName: String,
        approval: SyntheticCallerApproval? = null,
    ): GuardVerdict = GuardVerdict.deny(403, "NATIVE_SENSITIVE_PROFILE_DISABLED")

    /**
     * A held lease represents one in-flight HTTP request, not a caller
     * identity or device-mutating cross-process lease. Never persist it.
     */
    fun begin(request: LocalHttpRequest): GuardTicket {
        val decision = evaluate(request)
        if (!decision.allowed) return GuardTicket(decision)
        while (true) {
            val previous = active.get()
            if (previous >= maxInFlight) {
                return GuardTicket(GuardVerdict.deny(429, "NATIVE_BUSY"))
            }
            if (active.compareAndSet(previous, previous + 1)) {
                return GuardTicket(decision) { active.decrementAndGet() }
            }
        }
    }

    private fun localAuthority(input: String?): Boolean {
        if (input == null || input.length > 32) return false
        val match = AUTHORITY.matchEntire(input) ?: return false
        val port = match.groupValues[1]
        // ADB forward exposes the same on-device localhost listener under
        // an ephemeral host-side port. Only the loopback host is trusted
        // here, never the port as caller authentication.
        return port.isEmpty() || (port.toIntOrNull() ?: 0) in 1..65535
    }

    private fun localOrigin(input: String): Boolean {
        if (input.length > 64 || !input.startsWith("http://")) return false
        return localAuthority(input.removePrefix("http://"))
    }

    companion object {
        const val MAX_BODY_BYTES: Long = 128L * 1024
        private const val MAX_SYNTHETIC_NONCES = 256
        private val AUTHORITY = Regex("(?:127\\.0\\.0\\.1|localhost)(?::([0-9]{1,5}))?")
    }
}

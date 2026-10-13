package org.androidmcp.protocol

import java.util.UUID

/**
 * N6.d dual-Host contention simulation only; no real signed identity,
 * Host connection, ADB command, Android Tool or mutation executor.
 */
enum class DualHostLeaseState {
    FAKE_HELD, BUSY, DENIED, STALE, REPLAY, EXPIRED, UNCERTAIN,
    UNAVAILABLE, RELEASED, ALREADY_RELEASED, PAIRING_REQUIRED, UNSUPPORTED,
}

data class FakeLeaseRequest(
    val hostId: String,
    val nativeInstallation: String,
    val bootEpoch: String,
    val targetPackage: String,
    val planDigest: String,
    val requestId: String,
    val fence: Long,
    val ttlMs: Long = 10_000,
    val schemaVersion: Int = 2,
    val unknownRequired: Set<String> = emptySet(),
    val fakeSignatureVerified: Boolean = true,
) {
    override fun toString() = "FakeLeaseRequest([REDACTED])"
}

data class FakeLeaseRecovery(
    val highWater: Long,
    val uncertainFence: Long?,
    val nativeInstallation: String,
    val bootEpoch: String,
    val seenRequestIds: List<String> = emptyList(),
    val seenPlanDigests: List<String> = emptyList(),
) {
    override fun toString() = "FakeLeaseRecovery([REDACTED])"
}

data class FakeLeaseReceipt(
    val status: DualHostLeaseState,
    val fence: Long? = null,
) {
    fun encode(): String =
        "{\"schema_version\":2,\"status\":\"" + status.name.lowercase() +
            "\",\"synthetic_only\":true,\"mutation_executed\":false," +
            "\"automatic_retry\":false}"
}

/**
 * A one-target synthetic coordinator. The N6.c private journal is the
 * separately tested durable high-water component. The recovery object here
 * is an **injected fixture**, not an authorization or production journal.
 */
class NativeMultiHostLease(
    private val nativeInstallation: String,
    private val bootEpoch: String,
    private val allowedHosts: Set<String>,
    private val targetPackage: String,
    private val clock: () -> Long,
    recovery: FakeLeaseRecovery? = null,
) {
    private data class Active(
        val host: String,
        val requestId: String,
        val plan: String,
        val fence: Long,
        var expiresAt: Long,
    )
    val processEpoch: String = UUID.randomUUID().toString()
    private var stopped = false
    private var lastClock = -1L
    private var highWater = recovery?.highWater ?: 0
    private var uncertain = recovery?.uncertainFence
    // A recovered high-water with no replay evidence is not safe to resume:
    // a caller could repeat the same ambiguous action under a newer fence.
    // These are bounded injected fixtures, NOT authenticated durable storage.
    private val recoveredLedgerValid = recovery == null ||
        (recovery.seenRequestIds.size == recovery.seenPlanDigests.size &&
            recovery.seenRequestIds.size <= 64 &&
            (recovery.highWater == 0L || recovery.seenRequestIds.isNotEmpty()) &&
            (recovery.highWater != 0L || recovery.seenRequestIds.isEmpty()) &&
            recovery.seenRequestIds.all { REQUEST_ID.matches(it) } &&
            recovery.seenPlanDigests.all { DIGEST.matches(it) } &&
            recovery.seenRequestIds.toSet().size == recovery.seenRequestIds.size &&
            recovery.seenPlanDigests.toSet().size == recovery.seenPlanDigests.size)
    private val wrongRecoveredIdentity = recovery != null &&
        (!recoveredLedgerValid || recovery.nativeInstallation != nativeInstallation ||
            recovery.bootEpoch != bootEpoch || recovery.highWater < 0 ||
            (recovery.uncertainFence != null &&
                (recovery.uncertainFence <= 0 ||
                    recovery.uncertainFence > recovery.highWater)))
    private var active: Active? = null
    private var lastReleasedFence: Long? = null
    private val seenRequests = ArrayDeque<String>().apply {
        if (recoveredLedgerValid) recovery?.seenRequestIds?.forEach { addLast(it) }
    }
    private val seenPlans = ArrayDeque<String>().apply {
        if (recoveredLedgerValid) recovery?.seenPlanDigests?.forEach { addLast(it) }
    }

    @Synchronized
    fun acquire(request: FakeLeaseRequest): FakeLeaseReceipt {
        fun result(code: DualHostLeaseState) = FakeLeaseReceipt(code)
        if (stopped) return result(DualHostLeaseState.UNAVAILABLE)
        if (wrongRecoveredIdentity) return result(DualHostLeaseState.PAIRING_REQUIRED)
        val now = time() ?: return result(DualHostLeaseState.UNCERTAIN)
        val invalid = validate(request)
        if (invalid != null) return result(invalid)
        if (request.ttlMs !in 100..MAX_TTL_MS ||
            now > Long.MAX_VALUE - request.ttlMs
        ) return result(DualHostLeaseState.DENIED)
        val running = active
        if (running != null && now <= running.expiresAt) {
            return result(
                if (running.host == request.hostId &&
                    running.requestId == request.requestId
                ) DualHostLeaseState.REPLAY else DualHostLeaseState.BUSY,
            )
        }
        active = null
        if (request.fence <= highWater) return result(DualHostLeaseState.STALE)
        if (request.requestId in seenRequests || request.planDigest in seenPlans) {
            return result(DualHostLeaseState.REPLAY)
        }
        if (seenRequests.size == 64) seenRequests.removeFirst()
        if (seenPlans.size == 64) seenPlans.removeFirst()
        seenRequests.addLast(request.requestId)
        seenPlans.addLast(request.planDigest)
        highWater = request.fence
        active = Active(
            request.hostId, request.requestId, request.planDigest,
            request.fence, now + request.ttlMs,
        )
        return FakeLeaseReceipt(DualHostLeaseState.FAKE_HELD, request.fence)
    }

    @Synchronized
    fun renew(request: FakeLeaseRequest): DualHostLeaseState {
        if (stopped) return DualHostLeaseState.UNAVAILABLE
        if (wrongRecoveredIdentity) return DualHostLeaseState.PAIRING_REQUIRED
        val now = time() ?: return DualHostLeaseState.UNCERTAIN
        val current = active ?: return DualHostLeaseState.STALE
        val invalid = validate(request)
        if (invalid != null) return invalid
        if (current.host != request.hostId || current.fence != request.fence ||
            current.requestId != request.requestId ||
            current.plan != request.planDigest
        ) return DualHostLeaseState.DENIED
        if (now > current.expiresAt) {
            active = null
            return DualHostLeaseState.EXPIRED
        }
        if (request.ttlMs !in 100..MAX_TTL_MS ||
            now > Long.MAX_VALUE - request.ttlMs
        ) return DualHostLeaseState.DENIED
        current.expiresAt = now + request.ttlMs
        return DualHostLeaseState.FAKE_HELD
    }

    @Synchronized
    fun release(request: FakeLeaseRequest): DualHostLeaseState {
        if (stopped) return if (request.fence == uncertain) {
            DualHostLeaseState.UNCERTAIN
        } else DualHostLeaseState.UNAVAILABLE
        if (wrongRecoveredIdentity) return DualHostLeaseState.PAIRING_REQUIRED
        val now = time() ?: return DualHostLeaseState.UNCERTAIN
        val invalid = validate(request)
        if (invalid != null) return invalid
        val current = active
        if (current == null) return if (lastReleasedFence == request.fence) {
            DualHostLeaseState.ALREADY_RELEASED
        } else DualHostLeaseState.STALE
        if (current.host != request.hostId || current.fence != request.fence ||
            current.requestId != request.requestId ||
            current.plan != request.planDigest
        ) return DualHostLeaseState.DENIED
        if (now > current.expiresAt) {
            active = null
            return DualHostLeaseState.EXPIRED
        }
        active = null
        lastReleasedFence = request.fence
        return DualHostLeaseState.RELEASED
    }

    @Synchronized
    fun stop() {
        if (stopped) return
        stopped = true
        uncertain = active?.fence ?: uncertain
        active = null
    }

    @Synchronized
    fun simulateProcessDeath() = stop()

    @Synchronized
    fun recoverySnapshot() = FakeLeaseRecovery(
        highWater, uncertain, nativeInstallation, bootEpoch,
        seenRequests.toList(), seenPlans.toList(),
    )

    fun realDeviceMutationAllowed(): Boolean = false

    private fun validate(request: FakeLeaseRequest): DualHostLeaseState? {
        if (request.schemaVersion != 2 || request.unknownRequired.isNotEmpty()) {
            return DualHostLeaseState.UNSUPPORTED
        }
        if (!request.fakeSignatureVerified || request.hostId !in allowedHosts ||
            request.targetPackage != targetPackage || !IDENT.matches(request.hostId) ||
            request.requestId.length !in 1..128 ||
            !REQUEST_ID.matches(request.requestId) ||
            !DIGEST.matches(request.planDigest) || request.fence <= 0
        ) return DualHostLeaseState.DENIED
        if (request.nativeInstallation != nativeInstallation ||
            request.bootEpoch != bootEpoch
        ) return DualHostLeaseState.PAIRING_REQUIRED
        return null
    }

    private fun time(): Long? {
        val now = clock()
        if (now < 0 || (lastClock >= 0 && now < lastClock)) {
            stop()
            return null
        }
        lastClock = now
        return now
    }

    companion object {
        private const val MAX_TTL_MS = 30_000L
        private val IDENT = Regex("[A-Za-z0-9_-]{8,128}")
        private val REQUEST_ID = Regex("[A-Za-z0-9_-]{1,128}")
        private val DIGEST = Regex("[a-f0-9]{64}")
    }
}

package org.androidmcp.protocol

/**
 * Pure, deterministic lease-transition rules. This is a *model*, not an
 * authorization primitive, storage engine or exposed MCP/Android service.
 *
 * A future native service MUST authenticate the pairing and owner, supply its
 * own trusted monotonic clock and boot epoch, and persist the resulting state
 * atomically before granting any device mutation.
 */
data class LeaseSnapshot(
    val deviceId: String,
    val pairingId: String,
    val bootEpoch: String,
    val highFence: Long,
    val lastObservedMs: Long,
    val active: ActiveLease? = null,
)

data class ActiveLease(
    val ownerId: String,
    val planDigest: String,
    val requestId: String,
    val fence: Long,
    val expiresAtMs: Long,
)

data class LeaseRequest(
    val deviceId: String,
    val pairingId: String,
    val bootEpoch: String,
    val ownerId: String,
    val planDigest: String,
    val requestId: String,
    val fence: Long,
    val ttlMs: Long,
)

enum class LeaseRejectReason {
    INVALID_REQUEST,
    WRONG_DEVICE,
    WRONG_PAIRING,
    WRONG_BOOT,
    CLOCK_ROLLBACK,
    DEVICE_BUSY,
    STALE_FENCE,
    NOT_OWNER,
    LEASE_EXPIRED,
}

sealed interface LeaseDecision {
    data class Accepted(val next: LeaseSnapshot) : LeaseDecision
    data class Rejected(val reason: LeaseRejectReason) : LeaseDecision
}

object LeaseRules {
    private const val MAX_TTL_MS = 300_000L
    private val digestPattern = Regex("[0-9a-f]{64}")
    private val identifierPattern = Regex("[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")

    /** Never use a Host-supplied timestamp as the Native clock. */
    fun acquire(state: LeaseSnapshot, req: LeaseRequest, nativeNowMs: Long): LeaseDecision {
        val problem = validate(state, req, nativeNowMs)
        if (problem != null) return LeaseDecision.Rejected(problem)
        if (nativeNowMs < state.lastObservedMs) {
            return LeaseDecision.Rejected(LeaseRejectReason.CLOCK_ROLLBACK)
        }
        if (state.active != null && nativeNowMs < state.active.expiresAtMs) {
            return LeaseDecision.Rejected(LeaseRejectReason.DEVICE_BUSY)
        }
        if (req.fence <= state.highFence) {
            return LeaseDecision.Rejected(LeaseRejectReason.STALE_FENCE)
        }
        // The caller must persist this state before acknowledging acquisition.
        val next = state.copy(
            highFence = req.fence,
            lastObservedMs = nativeNowMs,
            active = ActiveLease(
                ownerId = req.ownerId,
                planDigest = req.planDigest,
                requestId = req.requestId,
                fence = req.fence,
                expiresAtMs = nativeNowMs + req.ttlMs,
            ),
        )
        return LeaseDecision.Accepted(next)
    }

    /** Release only the exact, still-current lease; never reset the fence. */
    fun release(
        state: LeaseSnapshot,
        ownerId: String,
        requestId: String,
        fence: Long,
        nativeNowMs: Long,
    ): LeaseDecision {
        if (nativeNowMs < state.lastObservedMs || nativeNowMs < 0) {
            return LeaseDecision.Rejected(LeaseRejectReason.CLOCK_ROLLBACK)
        }
        val active = state.active ?: return LeaseDecision.Rejected(LeaseRejectReason.NOT_OWNER)
        if (nativeNowMs >= active.expiresAtMs) {
            return LeaseDecision.Rejected(LeaseRejectReason.LEASE_EXPIRED)
        }
        if (ownerId != active.ownerId || requestId != active.requestId || fence != active.fence) {
            return LeaseDecision.Rejected(LeaseRejectReason.NOT_OWNER)
        }
        return LeaseDecision.Accepted(state.copy(active = null, lastObservedMs = nativeNowMs))
    }

    private fun validate(
        state: LeaseSnapshot,
        req: LeaseRequest,
        nativeNowMs: Long,
    ): LeaseRejectReason? {
        if (
            nativeNowMs < 0 ||
            req.fence <= 0 ||
            req.ttlMs <= 0 ||
            req.ttlMs > MAX_TTL_MS ||
            nativeNowMs > Long.MAX_VALUE - req.ttlMs ||
            !identifierPattern.matches(req.ownerId) ||
            !identifierPattern.matches(req.requestId) ||
            !digestPattern.matches(req.planDigest)
        ) {
            return LeaseRejectReason.INVALID_REQUEST
        }
        if (req.deviceId != state.deviceId) return LeaseRejectReason.WRONG_DEVICE
        if (req.pairingId != state.pairingId) return LeaseRejectReason.WRONG_PAIRING
        if (req.bootEpoch != state.bootEpoch) return LeaseRejectReason.WRONG_BOOT
        return null
    }
}

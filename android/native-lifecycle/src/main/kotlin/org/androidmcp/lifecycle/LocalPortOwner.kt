package org.androidmcp.lifecycle

/**
 * A process-local reservation for exactly one server socket owner.
 *
 * This cannot authenticate a peer, coordinate across processes, or replace
 * a Host/Native fencing lease. Failure to prove socket release retains the
 * owner in UNKNOWN until the same owner verifies closure (or process exits).
 */
enum class PortPhase {
    FREE,
    RESERVED,
    READY,
    STOPPING,
    UNKNOWN,
}

class LocalPortOwner {
    private var owner: Any? = null
    private var phase = PortPhase.FREE

    @Synchronized
    fun currentPhase(): PortPhase = phase

    @Synchronized
    fun ownedBy(candidate: Any): Boolean = owner === candidate

    @Synchronized
    fun reserve(candidate: Any): Boolean {
        if (phase != PortPhase.FREE) return false
        owner = candidate
        phase = PortPhase.RESERVED
        return true
    }

    @Synchronized
    fun confirmReady(candidate: Any): Boolean {
        if (owner !== candidate || phase != PortPhase.RESERVED) return false
        phase = PortPhase.READY
        return true
    }

    @Synchronized
    fun beginStop(candidate: Any): Boolean {
        // A duplicate shutdown cannot be started while an earlier stop is
        // pending. UNKNOWN remains retryable by the *same* original owner.
        if (owner !== candidate || phase == PortPhase.FREE || phase == PortPhase.STOPPING) {
            return false
        }
        phase = PortPhase.STOPPING
        return true
    }

    @Synchronized
    fun confirmStopped(candidate: Any, portVerifiedReleased: Boolean): Boolean {
        if (owner !== candidate || phase != PortPhase.STOPPING) return false
        if (!portVerifiedReleased) {
            phase = PortPhase.UNKNOWN
            return false
        }
        owner = null
        phase = PortPhase.FREE
        return true
    }
}

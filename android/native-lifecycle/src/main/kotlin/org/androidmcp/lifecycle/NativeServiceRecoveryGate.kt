package org.androidmcp.lifecycle

import java.util.UUID

/**
 * N7.d isolated, synthetic recovery/epoch state machine for user-visible MCP.
 * The production NativeServiceLifecycle owns real START/STOP/notifications;
 * this model provides only fake denial/epoch regression coverage, not a new
 * Android boot receiver, socket creator or credential issuer.
 */
enum class NativeRecoveryState { STOPPED, STARTING, RUNNING, STOPPING, UNKNOWN, BLOCKED, CRASHED }

data class SyntheticRecoveryStart(
    val api: Int = 36,
    val ownerId: String = "owner-one",
    val explicitUserStart: Boolean = true,
    val callerForeground: Boolean = true,
    val notificationGranted: Boolean = true,
    val oldListenerClosed: Boolean = true,
    val oldNotificationRemoved: Boolean = true,
)

data class NativeRecoveryReceipt(
    val status: NativeRecoveryState,
    val readinessProof: String? = null,
    val endpointLive: Boolean = false,
) {
    override fun toString() = "NativeRecoveryReceipt([REDACTED])"
}

/** No field authorizes real capture, caller challenges or Host/Native leases. */
data class SyntheticSensitiveEpochs(val capture: String, val challenge: String, val lease: String) {
    override fun toString() = "SyntheticSensitiveEpochs([REDACTED])"
}

class NativeServiceRecoveryGate {
    private var phase = NativeRecoveryState.STOPPED
    private var owner: String? = null
    private var pendingProof: String? = null
    private var sensitiveEpoch: SyntheticSensitiveEpochs? = null

    @Synchronized
    fun snapshot(): NativeRecoveryState = phase

    @Synchronized
    fun explicitStart(request: SyntheticRecoveryStart): NativeRecoveryReceipt {
        if (phase != NativeRecoveryState.STOPPED ||
            request.api !in setOf(34, 36) ||
            !request.explicitUserStart || !request.callerForeground ||
            !request.notificationGranted || !request.oldListenerClosed ||
            !request.oldNotificationRemoved || !OWNER_ID.matches(request.ownerId)
        ) return NativeRecoveryReceipt(NativeRecoveryState.BLOCKED)
        owner = request.ownerId
        pendingProof = UUID.randomUUID().toString()
        sensitiveEpoch = null
        phase = NativeRecoveryState.STARTING
        return NativeRecoveryReceipt(NativeRecoveryState.STARTING, pendingProof)
    }

    /** A caller must verify actual loopback port binding before invoking. */
    @Synchronized
    fun listenerReady(proof: String, portActuallyBound: Boolean): NativeRecoveryReceipt {
        if (phase != NativeRecoveryState.STARTING ||
            proof != pendingProof || !portActuallyBound
        ) return NativeRecoveryReceipt(NativeRecoveryState.BLOCKED)
        pendingProof = null
        sensitiveEpoch = SyntheticSensitiveEpochs(
            UUID.randomUUID().toString(), UUID.randomUUID().toString(), UUID.randomUUID().toString()
        )
        phase = NativeRecoveryState.RUNNING
        return NativeRecoveryReceipt(NativeRecoveryState.RUNNING, endpointLive = true)
    }

    @Synchronized
    fun stop(ownerId: String): NativeRecoveryReceipt {
        if (ownerId != owner || phase !in setOf(
                NativeRecoveryState.STARTING, NativeRecoveryState.RUNNING,
                NativeRecoveryState.UNKNOWN,
            )
        ) return NativeRecoveryReceipt(NativeRecoveryState.BLOCKED)
        // Invalidate fake sensitive sessions at *request*, not after shutdown.
        sensitiveEpoch = null
        pendingProof = null
        phase = NativeRecoveryState.STOPPING
        return NativeRecoveryReceipt(NativeRecoveryState.STOPPING)
    }

    @Synchronized
    fun confirmStopped(
        ownerId: String,
        portReleased: Boolean,
        notificationRemoved: Boolean,
    ): NativeRecoveryReceipt {
        if (ownerId != owner || phase != NativeRecoveryState.STOPPING) {
            return NativeRecoveryReceipt(NativeRecoveryState.BLOCKED)
        }
        if (!portReleased || !notificationRemoved) {
            phase = NativeRecoveryState.UNKNOWN
            return NativeRecoveryReceipt(NativeRecoveryState.UNKNOWN)
        }
        owner = null
        pendingProof = null
        sensitiveEpoch = null
        phase = NativeRecoveryState.STOPPED
        return NativeRecoveryReceipt(NativeRecoveryState.STOPPED)
    }

    @Synchronized
    fun onProcessKill(): NativeRecoveryReceipt {
        sensitiveEpoch = null
        pendingProof = null
        owner = null
        phase = NativeRecoveryState.CRASHED
        return NativeRecoveryReceipt(NativeRecoveryState.CRASHED)
    }

    @Synchronized
    fun onReboot(): NativeRecoveryReceipt {
        sensitiveEpoch = null
        pendingProof = null
        owner = null
        phase = NativeRecoveryState.STOPPED
        return NativeRecoveryReceipt(NativeRecoveryState.STOPPED)
    }

    /** START_NOT_STICKY; no null-Intent or boot receiver startup path. */
    fun implicitRestart(): NativeRecoveryReceipt =
        NativeRecoveryReceipt(NativeRecoveryState.BLOCKED)

    /** A test token; not a real sensitive capability or credential. */
    @Synchronized
    fun fakeSensitiveEpochs(): SyntheticSensitiveEpochs =
        if (phase == NativeRecoveryState.RUNNING) {
            requireNotNull(sensitiveEpoch)
        } else {
            throw IllegalStateException("No simulated running epoch")
        }

    @Synchronized
    fun fakeEpochsStillValid(snapshot: SyntheticSensitiveEpochs): Boolean =
        phase == NativeRecoveryState.RUNNING && sensitiveEpoch == snapshot

    fun realSensitiveResumeAllowed(): Boolean = false

    companion object {
        private val OWNER_ID = Regex("[A-Za-z0-9_-]{1,128}")
    }
}

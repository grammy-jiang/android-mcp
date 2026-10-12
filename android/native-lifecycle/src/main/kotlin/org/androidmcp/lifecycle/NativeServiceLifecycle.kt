package org.androidmcp.lifecycle

/**
 * Service-command ordering is separate from Android callbacks and MCP
 * transport. This pure Kotlin state model holds no socket or privilege.
 *
 * A command token is an operation epoch, not an authentication credential.
 * The Android Service must serialize actual start/stop effects and only call
 * completion after the listener has really reached the claimed state.
 */
enum class ServicePhase {
    STOPPED,
    STARTING,
    RUNNING,
    STOPPING,
    FAILED_CLOSED,
}

data class LifecycleSnapshot(val phase: ServicePhase, val generation: Long)

sealed interface LifecycleDecision {
    data class Execute(val generation: Long) : LifecycleDecision
    data object AlreadySatisfied : LifecycleDecision
    data object Blocked : LifecycleDecision
}

class NativeServiceLifecycle(initialGeneration: Long = 0L) {
    init {
        require(initialGeneration >= 0) { "Generation must be nonnegative" }
    }

    private var generation = initialGeneration
    private var phase = ServicePhase.STOPPED

    @Synchronized
    fun snapshot() = LifecycleSnapshot(phase, generation)

    /**
     * An outstanding stop is never cancelled by a new start. Callers can
     * explicitly retry after the stop has been confirmed.
     */
    @Synchronized
    fun requestStart(): LifecycleDecision = when (phase) {
        ServicePhase.STOPPED -> issue(ServicePhase.STARTING)
        ServicePhase.STARTING, ServicePhase.RUNNING -> LifecycleDecision.AlreadySatisfied
        ServicePhase.STOPPING, ServicePhase.FAILED_CLOSED -> LifecycleDecision.Blocked
    }

    /**
     * STOP while STARTING is accepted and must queue behind the in-flight
     * start on the *same* Android worker. A previous completion callback
     * cannot then promote the service to RUNNING.
     */
    @Synchronized
    fun requestStop(): LifecycleDecision = when (phase) {
        ServicePhase.STOPPED, ServicePhase.STOPPING -> LifecycleDecision.AlreadySatisfied
        ServicePhase.STARTING, ServicePhase.RUNNING, ServicePhase.FAILED_CLOSED ->
            issue(ServicePhase.STOPPING)
    }

    @Synchronized
    fun started(token: Long): Boolean =
        completeIfCurrent(token, ServicePhase.STARTING, ServicePhase.RUNNING)

    @Synchronized
    fun startFailed(token: Long): Boolean =
        completeIfCurrent(token, ServicePhase.STARTING, ServicePhase.FAILED_CLOSED)

    /** Call only *after* a verified listener shutdown, not at stop request. */
    @Synchronized
    fun stopped(token: Long): Boolean =
        completeIfCurrent(token, ServicePhase.STOPPING, ServicePhase.STOPPED)

    @Synchronized
    fun stopFailed(token: Long): Boolean =
        completeIfCurrent(token, ServicePhase.STOPPING, ServicePhase.FAILED_CLOSED)

    private fun completeIfCurrent(
        token: Long,
        expected: ServicePhase,
        next: ServicePhase,
    ): Boolean {
        if (generation != token || phase != expected) return false
        phase = next
        return true
    }

    private fun issue(next: ServicePhase): LifecycleDecision {
        if (generation == Long.MAX_VALUE) {
            phase = ServicePhase.FAILED_CLOSED
            return LifecycleDecision.Blocked
        }
        generation += 1
        phase = next
        return LifecycleDecision.Execute(generation)
    }
}

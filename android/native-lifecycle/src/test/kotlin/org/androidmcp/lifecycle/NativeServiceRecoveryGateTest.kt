package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeServiceRecoveryGateTest {
    private fun startRunning(policy: NativeServiceRecoveryGate): String {
        val accepted = policy.explicitStart(SyntheticRecoveryStart())
        assertEquals(NativeRecoveryState.STARTING, accepted.status)
        assertFalse(accepted.endpointLive)
        val proof = accepted.readinessProof!!
        assertEquals(NativeRecoveryState.RUNNING,
            policy.listenerReady(proof, portActuallyBound = true).status)
        return proof
    }

    @Test
    fun tN7D01ExplicitUserRestartAfterVerifiedStopRequiresFreshReadinessProof() {
        val policy = NativeServiceRecoveryGate()
        val first = startRunning(policy)
        assertEquals(NativeRecoveryState.STOPPING, policy.stop("owner-one").status)
        assertEquals(NativeRecoveryState.UNKNOWN,
            policy.confirmStopped("owner-one", portReleased = false,
                notificationRemoved = true).status)
        assertEquals(NativeRecoveryState.BLOCKED,
            policy.explicitStart(SyntheticRecoveryStart()).status)
        assertEquals(NativeRecoveryState.STOPPING, policy.stop("owner-one").status)
        assertEquals(NativeRecoveryState.STOPPED,
            policy.confirmStopped("owner-one", portReleased = true,
                notificationRemoved = true).status)
        val restarted = policy.explicitStart(SyntheticRecoveryStart())
        assertEquals(NativeRecoveryState.STARTING, restarted.status)
        assertFalse(first == restarted.readinessProof)
        assertEquals(NativeRecoveryState.BLOCKED,
            policy.listenerReady(first, portActuallyBound = true).status)
        assertEquals(NativeRecoveryState.RUNNING,
            policy.listenerReady(restarted.readinessProof!!, portActuallyBound = true).status)
    }

    @Test
    fun tN7D02ProcessKillRebootOrStickyRestartNeverResurrectPort() {
        val policy = NativeServiceRecoveryGate()
        startRunning(policy)
        assertEquals(NativeRecoveryState.CRASHED, policy.onProcessKill().status)
        assertEquals(NativeRecoveryState.BLOCKED, policy.implicitRestart().status)
        assertEquals(NativeRecoveryState.STOPPED, policy.onReboot().status)
        assertEquals(NativeRecoveryState.STOPPED, policy.snapshot())
        assertEquals(NativeRecoveryState.BLOCKED, policy.implicitRestart().status)
        assertFalse(policy.realSensitiveResumeAllowed())
    }

    @Test
    fun tN7D03UnreleasedPortFailedNotificationOrSecondOwnerCollisionFailClosed() {
        val policy = NativeServiceRecoveryGate()
        startRunning(policy)
        assertEquals(NativeRecoveryState.BLOCKED,
            policy.stop("another-host").status)
        assertEquals(NativeRecoveryState.STOPPING, policy.stop("owner-one").status)
        assertEquals(NativeRecoveryState.UNKNOWN,
            policy.confirmStopped("owner-one", portReleased = true,
                notificationRemoved = false).status)
        assertEquals(NativeRecoveryState.BLOCKED,
            policy.explicitStart(SyntheticRecoveryStart(ownerId = "another-host")).status)
        assertEquals(NativeRecoveryState.STOPPING, policy.stop("owner-one").status)
        assertEquals(NativeRecoveryState.STOPPED,
            policy.confirmStopped("owner-one", portReleased = true,
                notificationRemoved = true).status)
    }

    @Test
    fun tN7D04Api30_33RejectFgsApi34_36RequireNotificationAndForeground() {
        for (api in listOf(30, 33)) {
            assertEquals(NativeRecoveryState.BLOCKED,
                NativeServiceRecoveryGate().explicitStart(SyntheticRecoveryStart(api = api)).status)
        }
        for (api in listOf(34, 36)) {
            assertEquals(NativeRecoveryState.STARTING,
                NativeServiceRecoveryGate().explicitStart(SyntheticRecoveryStart(api = api)).status)
            for (bad in listOf(
                SyntheticRecoveryStart(api = api, explicitUserStart = false),
                SyntheticRecoveryStart(api = api, notificationGranted = false),
                SyntheticRecoveryStart(api = api, callerForeground = false),
            )) {
                assertEquals(NativeRecoveryState.BLOCKED,
                    NativeServiceRecoveryGate().explicitStart(bad).status)
            }
        }
    }

    @Test
    fun tN7D05FakeCaptureChallengeAndLeaseEpochInvalidatedByRestart() {
        val policy = NativeServiceRecoveryGate()
        startRunning(policy)
        val issued = policy.fakeSensitiveEpochs()
        assertTrue(policy.fakeEpochsStillValid(issued))
        assertEquals(NativeRecoveryState.STOPPING, policy.stop("owner-one").status)
        assertFalse(policy.fakeEpochsStillValid(issued))
        assertEquals(NativeRecoveryState.STOPPED,
            policy.confirmStopped("owner-one", true, true).status)
        startRunning(policy)
        val replacement = policy.fakeSensitiveEpochs()
        assertFalse(issued == replacement)
        assertFalse(policy.fakeEpochsStillValid(issued))
        assertTrue(policy.fakeEpochsStillValid(replacement))
        assertFalse(policy.realSensitiveResumeAllowed())
    }

    @Test
    fun tN7D06NoAutoWakeBootReceiverOrExternalPortInRecoveryModel() {
        val policy = NativeServiceRecoveryGate()
        assertEquals(NativeRecoveryState.STOPPED, policy.snapshot())
        assertEquals(NativeRecoveryState.BLOCKED, policy.implicitRestart().status)
        assertEquals(NativeRecoveryState.BLOCKED,
            policy.explicitStart(SyntheticRecoveryStart(explicitUserStart = false)).status)
        assertFalse(policy.realSensitiveResumeAllowed())
    }

    @Test
    fun wrongProofCannotClaimPortReadinessOrReanimateSensitiveTokens() {
        val recovery = NativeServiceRecoveryGate()
        val ticket = recovery.explicitStart(SyntheticRecoveryStart())
        assertEquals(NativeRecoveryState.STARTING, ticket.status)
        assertEquals(NativeRecoveryState.BLOCKED,
            recovery.listenerReady("stale-or-foreign-token", portActuallyBound = true).status)
        assertEquals(NativeRecoveryState.BLOCKED,
            recovery.listenerReady(ticket.readinessProof!!, portActuallyBound = false).status)
        assertEquals(NativeRecoveryState.STARTING, recovery.snapshot())
        assertEquals(NativeRecoveryState.RUNNING,
            recovery.listenerReady(ticket.readinessProof, portActuallyBound = true).status)
        val old = recovery.fakeSensitiveEpochs()
        recovery.onProcessKill()
        assertFalse(recovery.fakeEpochsStillValid(old))
        assertEquals(NativeRecoveryState.BLOCKED,
            recovery.listenerReady(ticket.readinessProof, portActuallyBound = true).status)
        assertFalse(recovery.realSensitiveResumeAllowed())
    }

    @Test
    fun concurrentDuplicateExplicitStartsHaveOneOwnerAndOneProof() {
        val gate = NativeServiceRecoveryGate()
        val executor = java.util.concurrent.Executors.newFixedThreadPool(10)
        val signal = java.util.concurrent.CountDownLatch(1)
        try {
            val tasks = (1..10).map {
                executor.submit<NativeRecoveryReceipt> {
                    signal.await(5, java.util.concurrent.TimeUnit.SECONDS)
                    gate.explicitStart(SyntheticRecoveryStart())
                }
            }
            signal.countDown()
            val outputs = tasks.map { it.get(5, java.util.concurrent.TimeUnit.SECONDS) }
            assertEquals(1, outputs.count { it.status == NativeRecoveryState.STARTING })
            assertEquals(9, outputs.count { it.status == NativeRecoveryState.BLOCKED })
            assertEquals(NativeRecoveryState.STARTING, gate.snapshot())
            assertFalse(gate.realSensitiveResumeAllowed())
        } finally { signal.countDown(); executor.shutdownNow() }
    }
}

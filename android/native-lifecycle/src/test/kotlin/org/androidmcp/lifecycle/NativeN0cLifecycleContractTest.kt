package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertInstanceOf
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * N0.c source-level lifecycle contract. Real service/notification, socket,
 * and Android API 30/33/34/36 behavior are verified separately on real AVDs.
 */
class NativeN0cLifecycleContractTest {
    private fun NativeServiceLifecycle.startIssued(): Long =
        assertInstanceOf(LifecycleDecision.Execute::class.java, requestStart()).generation

    private fun NativeServiceLifecycle.stopIssued(): Long =
        assertInstanceOf(LifecycleDecision.Execute::class.java, requestStop()).generation

    @Test
    fun tN0C01ActivityAndFgServiceModesShareExactlyOnePortOwner() {
        val port = LocalPortOwner()
        val activity = Any()
        val service = Any()
        val fgs = NativeServiceLifecycle()
        assertTrue(port.reserve(activity))
        assertTrue(port.confirmReady(activity))
        val failedStart = fgs.startIssued()
        assertFalse(port.reserve(service))
        assertTrue(fgs.startFailed(failedStart))
        assertEquals(ServicePhase.FAILED_CLOSED, fgs.snapshot().phase)
        assertEquals(LifecycleDecision.Blocked, fgs.requestStart())
        val cleanup = fgs.stopIssued()
        assertTrue(fgs.stopped(cleanup))
        assertTrue(port.beginStop(activity))
        assertTrue(port.confirmStopped(activity, true))
        assertTrue(port.reserve(service))
        val fresh = fgs.startIssued()
        assertTrue(port.confirmReady(service))
        assertTrue(fgs.started(fresh))
        assertEquals(ServicePhase.RUNNING, fgs.snapshot().phase)
    }

    @Test
    fun tN0C02CompetingActivityCannotStealOrReleaseFgServiceListener() {
        val owner = LocalPortOwner()
        val foreground = Any()
        val competingActivity = Any()
        assertTrue(owner.reserve(foreground))
        assertTrue(owner.confirmReady(foreground))
        assertFalse(owner.reserve(competingActivity))
        assertFalse(owner.confirmReady(competingActivity))
        assertFalse(owner.beginStop(competingActivity))
        assertFalse(owner.confirmStopped(competingActivity, true))
        assertEquals(PortPhase.READY, owner.currentPhase())
        assertTrue(owner.ownedBy(foreground))
    }

    @Test
    fun tN0C03ShutdownFailureWithBoundPortRemainsUnknown() {
        val owner = LocalPortOwner()
        val foreground = Any()
        assertTrue(owner.reserve(foreground))
        assertTrue(owner.confirmReady(foreground))
        assertTrue(owner.beginStop(foreground))
        // Production Ktor exception or still-bound socket must be passed as
        // an unverified release, never as a successful cleanup.
        assertFalse(owner.confirmStopped(foreground, false))
        assertEquals(PortPhase.UNKNOWN, owner.currentPhase())
        assertFalse(owner.reserve(Any()))
        assertTrue(owner.ownedBy(foreground))
        assertFalse(owner.confirmReady(foreground))
        assertTrue(owner.beginStop(foreground))
        assertTrue(owner.confirmStopped(foreground, true))
    }

    @Test
    fun tN0C04StopInProgressCannotBeginDuplicateShutdown() {
        val owner = LocalPortOwner()
        val service = Any()
        assertTrue(owner.reserve(service))
        assertTrue(owner.confirmReady(service))
        assertTrue(owner.beginStop(service))
        assertEquals(PortPhase.STOPPING, owner.currentPhase())
        // RED on the old implementation: a second caller could begin
        // shutdown again while the first shutdown had not finished.
        assertFalse(owner.beginStop(service))
        assertFalse(owner.reserve(Any()))
        assertTrue(owner.confirmStopped(service, true))
        assertFalse(owner.beginStop(service))
    }

    @Test
    fun tN0C05AndroidApiAndExplicitServiceStopNeverAutoRestart() {
        assertFalse(NativeForegroundSupport.supported(30))
        assertFalse(NativeForegroundSupport.supported(33))
        assertTrue(NativeForegroundSupport.supported(34))
        assertTrue(NativeForegroundSupport.supported(36))
        val model = NativeServiceLifecycle()
        val started = model.startIssued()
        assertTrue(model.started(started))
        val stopped = model.stopIssued()
        assertTrue(model.stopped(stopped))
        // Simulates completed user Stop, without inventing a BOOT or process
        // resurrection transition. Real Android API tests remain required.
        repeat(12) {
            assertEquals(ServicePhase.STOPPED, model.snapshot().phase)
            assertEquals(stopped, model.snapshot().generation)
        }
    }

    @Test
    fun tN0C06ConcurrentStopStartCannotLeaveSecondListenerOrOrphan() {
        val owner = LocalPortOwner()
        val activity = Any()
        val fgs = Any()
        val lifecycle = NativeServiceLifecycle()
        assertTrue(owner.reserve(activity))
        val start = lifecycle.startIssued()
        val stop = lifecycle.stopIssued()
        assertEquals(LifecycleDecision.Blocked, lifecycle.requestStart())
        assertFalse(lifecycle.started(start))
        assertFalse(owner.reserve(fgs))
        assertTrue(owner.beginStop(activity))
        assertFalse(owner.confirmStopped(activity, false))
        assertEquals(PortPhase.UNKNOWN, owner.currentPhase())
        assertFalse(owner.reserve(fgs))
        assertFalse(lifecycle.stopped(start))
        assertTrue(owner.beginStop(activity))
        assertTrue(owner.confirmStopped(activity, true))
        assertTrue(lifecycle.stopped(stop))
        assertEquals(ServicePhase.STOPPED, lifecycle.snapshot().phase)
        assertTrue(owner.reserve(fgs))
        assertFalse(owner.reserve(activity))
        assertTrue(owner.beginStop(fgs))
        assertTrue(owner.confirmStopped(fgs, true))
        assertEquals(PortPhase.FREE, owner.currentPhase())
    }

    @Test
    fun competingStopRequestsKeepOwnershipUntilAVerifiedCompletion() {
        val owner = LocalPortOwner()
        val candidate = Any()
        assertTrue(owner.reserve(candidate))
        assertTrue(owner.confirmReady(candidate))
        val executor = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val start = CountDownLatch(1)
        try {
            val results = (1..8).map {
                executor.submit<Boolean> {
                    ready.countDown()
                    start.await(5, TimeUnit.SECONDS)
                    owner.beginStop(candidate)
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            start.countDown()
            // Exactly one stop operation can be admitted until the first
            // caller proves the listener closed. Never release from a
            // duplicate stop, even if Ktor shutdown is slow.
            assertEquals(1, results.count { it.get(5, TimeUnit.SECONDS) })
            assertEquals(PortPhase.STOPPING, owner.currentPhase())
            assertFalse(owner.reserve(Any()))
            assertTrue(owner.confirmStopped(candidate, true))
        } finally {
            start.countDown()
            executor.shutdownNow()
        }
    }
}

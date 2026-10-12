package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertInstanceOf
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class NativeServiceLifecycleTest {
    private fun started(model: NativeServiceLifecycle): Long {
        val token = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStart())
            .generation
        assertTrue(model.started(token))
        return token
    }

    private fun stopped(model: NativeServiceLifecycle): Long {
        val token = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStop())
            .generation
        assertTrue(model.stopped(token))
        return token
    }

    @Test
    fun startsOnlyAfterConfirmation() {
        val model = NativeServiceLifecycle()
        val token = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStart())
            .generation
        assertEquals(ServicePhase.STARTING, model.snapshot().phase)
        assertEquals(LifecycleDecision.AlreadySatisfied, model.requestStart())
        assertTrue(model.started(token))
        assertEquals(ServicePhase.RUNNING, model.snapshot().phase)
        assertEquals(LifecycleDecision.AlreadySatisfied, model.requestStart())
    }

    @Test
    fun stopBeforeStartDoesNotIssueACommand() {
        val model = NativeServiceLifecycle()
        assertEquals(LifecycleDecision.AlreadySatisfied, model.requestStop())
        assertEquals(ServicePhase.STOPPED, model.snapshot().phase)
    }

    @Test
    fun stopDuringStartSupersedesOldCompletion() {
        val model = NativeServiceLifecycle()
        val first = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStart())
            .generation
        val stop = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStop())
            .generation
        assertEquals(ServicePhase.STOPPING, model.snapshot().phase)
        assertFalse(model.started(first))
        assertFalse(model.startFailed(first))
        assertEquals(LifecycleDecision.Blocked, model.requestStart())
        assertTrue(model.stopped(stop))
        assertEquals(ServicePhase.STOPPED, model.snapshot().phase)
    }

    @Test
    fun stopDuringRunningAndStartDuringStopAreOrdered() {
        val model = NativeServiceLifecycle()
        val first = started(model)
        val stop = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStop())
            .generation
        assertEquals(LifecycleDecision.AlreadySatisfied, model.requestStop())
        assertEquals(LifecycleDecision.Blocked, model.requestStart())
        assertFalse(model.stopped(first))
        assertTrue(model.stopped(stop))
        val next = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStart())
            .generation
        assertTrue(next > stop)
        assertTrue(model.started(next))
        assertEquals(ServicePhase.RUNNING, model.snapshot().phase)
    }

    @Test
    fun startFailureIsFailClosedUntilExplicitVerifiedStop() {
        val model = NativeServiceLifecycle()
        val token = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStart())
            .generation
        assertTrue(model.startFailed(token))
        assertEquals(ServicePhase.FAILED_CLOSED, model.snapshot().phase)
        assertEquals(LifecycleDecision.Blocked, model.requestStart())
        stopped(model)
        assertEquals(ServicePhase.STOPPED, model.snapshot().phase)
    }

    @Test
    fun stopFailureRemainsFailClosedAndAllowsExplicitRetry() {
        val model = NativeServiceLifecycle()
        started(model)
        val stop = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStop())
            .generation
        assertTrue(model.stopFailed(stop))
        assertEquals(ServicePhase.FAILED_CLOSED, model.snapshot().phase)
        assertEquals(LifecycleDecision.Blocked, model.requestStart())
        val retry = assertInstanceOf(LifecycleDecision.Execute::class.java, model.requestStop())
            .generation
        assertTrue(retry > stop)
        assertFalse(model.stopped(stop))
        assertTrue(model.stopped(retry))
        assertEquals(ServicePhase.STOPPED, model.snapshot().phase)
    }

    @Test
    fun staleOrDuplicateCallbacksNeverAdvanceState() {
        val model = NativeServiceLifecycle()
        val first = started(model)
        assertFalse(model.started(first))
        val stop = stopped(model)
        assertFalse(model.stopped(stop))
        assertFalse(model.stopFailed(stop))
        val second = started(model)
        assertFalse(model.startFailed(first))
        assertFalse(model.stopped(stop))
        assertEquals(ServicePhase.RUNNING, model.snapshot().phase)
        assertTrue(second > first)
    }

    @Test
    fun epochOverflowCannotWrapOrStart() {
        val model = NativeServiceLifecycle(Long.MAX_VALUE)
        assertEquals(LifecycleDecision.Blocked, model.requestStart())
        assertEquals(ServicePhase.FAILED_CLOSED, model.snapshot().phase)
        assertEquals(LifecycleDecision.Blocked, model.requestStop())
        assertEquals(Long.MAX_VALUE, model.snapshot().generation)
        assertThrows(IllegalArgumentException::class.java) { NativeServiceLifecycle(-1) }
    }

    @Test
    fun rapidSequentialTransitionsHaveStrictlyIncreasingEpochs() {
        val model = NativeServiceLifecycle()
        var previous = 0L
        repeat(100) {
            val start = started(model)
            val stop = stopped(model)
            assertTrue(start > previous)
            assertTrue(stop > start)
            previous = stop
        }
        assertEquals(ServicePhase.STOPPED, model.snapshot().phase)
        assertEquals(200L, model.snapshot().generation)
    }

    @Test
    fun concurrentDuplicateStartsIssueExactlyOneCommand() {
        val model = NativeServiceLifecycle()
        val pool = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val begin = CountDownLatch(1)
        try {
            val futures = (1..8).map {
                pool.submit<LifecycleDecision> {
                    ready.countDown()
                    begin.await(5, TimeUnit.SECONDS)
                    model.requestStart()
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            begin.countDown()
            val results = futures.map { it.get(5, TimeUnit.SECONDS) }
            assertEquals(1, results.count { it is LifecycleDecision.Execute })
            assertEquals(7, results.count { it == LifecycleDecision.AlreadySatisfied })
            assertEquals(ServicePhase.STARTING, model.snapshot().phase)
        } finally {
            begin.countDown()
            pool.shutdownNow()
        }
    }
}

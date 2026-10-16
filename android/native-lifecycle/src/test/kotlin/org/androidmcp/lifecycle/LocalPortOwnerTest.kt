package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class LocalPortOwnerTest {
    @Test
    fun onlyOneOfTwoModesCanReservePort() {
        val owner = LocalPortOwner()
        val activity = Any()
        val foreground = Any()
        assertTrue(owner.reserve(activity))
        assertTrue(owner.ownedBy(activity))
        assertFalse(owner.ownedBy(foreground))
        assertEquals(PortPhase.RESERVED, owner.currentPhase())
        assertFalse(owner.reserve(foreground))
        assertTrue(owner.confirmReady(activity))
        assertEquals(PortPhase.READY, owner.currentPhase())
        assertFalse(owner.confirmReady(foreground))
    }

    @Test
    fun onlyOwnerCanReleaseAfterVerifiedShutdown() {
        val owner = LocalPortOwner()
        val activity = Any()
        val foreground = Any()
        assertTrue(owner.reserve(activity))
        assertTrue(owner.confirmReady(activity))
        assertFalse(owner.beginStop(foreground))
        assertFalse(owner.confirmStopped(foreground, true))
        assertFalse(owner.reserve(foreground))
        assertTrue(owner.beginStop(activity))
        assertFalse(owner.reserve(foreground))
        assertTrue(owner.confirmStopped(activity, true))
        assertEquals(PortPhase.FREE, owner.currentPhase())
        assertTrue(owner.reserve(foreground))
    }

    @Test
    fun uncertainStopIsFailClosedUntilProvenFree() {
        val owner = LocalPortOwner()
        val activity = Any()
        val foreground = Any()
        assertTrue(owner.reserve(activity))
        assertTrue(owner.confirmReady(activity))
        assertTrue(owner.beginStop(activity))
        assertFalse(owner.confirmStopped(activity, false))
        assertEquals(PortPhase.UNKNOWN, owner.currentPhase())
        assertFalse(owner.reserve(foreground))
        assertFalse(owner.confirmReady(activity))
        assertTrue(owner.beginStop(activity))
        assertTrue(owner.confirmStopped(activity, true))
        assertTrue(owner.reserve(foreground))
    }

    @Test
    fun startFailureBeforeListeningCanReleaseOnlyAfterPortProof() {
        val owner = LocalPortOwner()
        val activity = Any()
        assertTrue(owner.reserve(activity))
        assertTrue(owner.beginStop(activity))
        assertFalse(owner.confirmStopped(activity, false))
        assertEquals(PortPhase.UNKNOWN, owner.currentPhase())
        assertTrue(owner.beginStop(activity))
        assertTrue(owner.confirmStopped(activity, true))
        assertEquals(PortPhase.FREE, owner.currentPhase())
    }

    @Test
    fun anotherOwnerCannotClearUnknownPort() {
        val owner = LocalPortOwner()
        val first = Any()
        val second = Any()
        assertTrue(owner.reserve(first))
        assertTrue(owner.beginStop(first))
        assertFalse(owner.confirmStopped(first, false))
        assertFalse(owner.beginStop(second))
        assertFalse(owner.confirmStopped(second, true))
        assertFalse(owner.reserve(second))
        assertEquals(PortPhase.UNKNOWN, owner.currentPhase())
    }

    @Test
    fun doubleStopOrStaleCallbackDoesNotClearNewOwner() {
        val owner = LocalPortOwner()
        val first = Any()
        val second = Any()
        assertTrue(owner.reserve(first))
        assertTrue(owner.beginStop(first))
        assertTrue(owner.confirmStopped(first, true))
        assertFalse(owner.confirmStopped(first, true))
        assertTrue(owner.reserve(second))
        assertFalse(owner.beginStop(first))
        assertFalse(owner.confirmStopped(first, true))
        assertEquals(PortPhase.RESERVED, owner.currentPhase())
    }

    @Test
    fun eightCompetingCallersGetOneReservation() {
        val owner = LocalPortOwner()
        val pool = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val begin = CountDownLatch(1)
        try {
            val futures = (1..8).map {
                pool.submit<Boolean> {
                    ready.countDown()
                    begin.await(5, TimeUnit.SECONDS)
                    owner.reserve(Any())
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            begin.countDown()
            assertEquals(1, futures.count { it.get(5, TimeUnit.SECONDS) })
        } finally {
            begin.countDown()
            pool.shutdownNow()
        }
    }

    @Test
    fun repeatedPortContentionKeepsUncertainShutdownFailClosed() {
        val owner = LocalPortOwner()
        val pool = Executors.newFixedThreadPool(8)
        try {
            repeat(100) {
                val candidates = List(8) { Any() }
                val ready = CountDownLatch(candidates.size)
                val begin = CountDownLatch(1)
                try {
                    val futures = candidates.map { candidate ->
                        pool.submit<Boolean> {
                            ready.countDown()
                            begin.await(5, TimeUnit.SECONDS) && owner.reserve(candidate)
                        }
                    }
                    assertTrue(ready.await(5, TimeUnit.SECONDS))
                    begin.countDown()
                    val winners = candidates.zip(futures).filter { (_, future) ->
                        future.get(5, TimeUnit.SECONDS)
                    }.map { (candidate, _) -> candidate }
                    assertEquals(1, winners.size)
                    val winner = winners.single()
                    assertTrue(owner.confirmReady(winner))
                    assertTrue(owner.beginStop(winner))
                    assertFalse(owner.confirmStopped(winner, false))
                    assertEquals(PortPhase.UNKNOWN, owner.currentPhase())
                    assertFalse(owner.reserve(Any()))
                    assertTrue(owner.beginStop(winner))
                    assertTrue(owner.confirmStopped(winner, true))
                    assertEquals(PortPhase.FREE, owner.currentPhase())
                } finally {
                    begin.countDown()
                }
            }
        } finally {
            pool.shutdownNow()
        }
    }
}

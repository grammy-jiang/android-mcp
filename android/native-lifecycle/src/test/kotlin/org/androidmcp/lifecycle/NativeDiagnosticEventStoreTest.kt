package org.androidmcp.lifecycle

import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class NativeDiagnosticEventStoreTest {
    @TempDir lateinit var privateRoot: Path
    private val now = AtomicLong(1000)
    private fun store() = NativeDiagnosticEventStore(privateRoot, now::get)

    @Test
    fun tN5C01CoarseDiagnosticEventsGetMonotonicIdTimestampAndAllowedOrigin() {
        store().use { owner ->
            val first = owner.append("event-001", OwnEventOrigin.ACTIVITY, OwnEventKind.STARTED)
            now.set(1500)
            val second = owner.append(
                "event-002", OwnEventOrigin.FOREGROUND_SERVICE, OwnEventKind.CRASH,
                OwnEventSensitivity.REDACTED_PRIVATE,
            )
            assertEquals(OwnEventState.APPENDED, first.state)
            assertEquals(1L, first.event!!.id)
            assertEquals(1000L, first.event.elapsedMs)
            assertEquals(2L, second.event!!.id)
            assertEquals(1500L, second.event.elapsedMs)
            assertEquals(OwnEventSensitivity.REDACTED_PRIVATE, second.event.sensitivity)
            val token = owner.openFakeSubscriber("this-app-owner", true)!!
            val page = owner.page(token)
            assertEquals(OwnEventPageState.AVAILABLE, page.state)
            assertEquals(listOf(1L, 2L), page.events.map { it.id })
            val metadata = page.encode()
            assertTrue(metadata.contains("redacted_private"))
            assertFalse(metadata.contains("stacktrace"))
            assertTrue(metadata.toByteArray().size < 16_384)
        }
    }

    @Test
    fun tN5C02DuplicateAndLateAckNeverAdvanceAnUnservedCursor() {
        store().use { owner ->
            for (i in 1..12) {
                now.set(1000L + i)
                assertEquals(OwnEventState.APPENDED,
                    owner.append("nonce-$i", OwnEventOrigin.APPLICATION, OwnEventKind.ANR).state)
            }
            assertEquals(OwnEventState.DUPLICATE,
                owner.append("nonce-1", OwnEventOrigin.APPLICATION, OwnEventKind.ANR).state)
            assertEquals(12, owner.pendingCount())
            val token = owner.openFakeSubscriber("same-app", true)!!
            val pageOne = owner.page(token, limit = 5)
            assertEquals(5, pageOne.events.size)
            assertEquals(OwnEventAckState.DENIED, owner.acknowledge(token, 12))
            assertEquals(OwnEventAckState.ACKNOWLEDGED, owner.acknowledge(token, 5))
            assertEquals(OwnEventAckState.ALREADY_ACKED, owner.acknowledge(token, 5))
            val pageTwo = owner.page(token, pageOne.nextCursor, limit = 5)
            assertEquals(listOf(6L, 7L, 8L, 9L, 10L), pageTwo.events.map { it.id })
            assertEquals(OwnEventAckState.ACKNOWLEDGED, owner.acknowledge(token, 10))
            assertEquals(2, owner.pendingCount())
        }
    }

    @Test
    fun tN5C03SimulatedProcessDeathReopensPendingNotConfirmedDelivered() {
        val original = store()
        val priorToken = original.openFakeSubscriber("owner", true)!!
        original.append("durable-1", OwnEventOrigin.ACTIVITY, OwnEventKind.STARTED)
        now.set(2000)
        original.append("durable-2", OwnEventOrigin.FOREGROUND_SERVICE, OwnEventKind.CRASH)
        val page = original.page(priorToken)
        assertEquals(2, page.events.size)
        original.simulateProcessDeath()
        store().use { restarted ->
            assertNotEquals(original.processEpoch, restarted.processEpoch)
            assertEquals(OwnEventPageState.DENIED, restarted.page(priorToken).state)
            assertEquals(OwnEventAckState.DENIED, restarted.acknowledge(priorToken, 2))
            assertEquals(2, restarted.pendingCount())
            val next = restarted.openFakeSubscriber("owner", true)!!
            val recovered = restarted.page(next)
            assertEquals(listOf(1L, 2L), recovered.events.map { it.id })
            assertEquals(OwnEventPageState.UNCERTAIN, recovered.state)
            assertEquals(OwnEventAckState.ACKNOWLEDGED,
                restarted.acknowledge(next, 2))
            assertEquals(0, restarted.pendingCount())
            now.set(2200)
            assertEquals(3L, restarted.append(
                "durable-3", OwnEventOrigin.APPLICATION, OwnEventKind.STOPPED).event!!.id)
        }
    }

    @Test
    fun tN5C04ExpirationCapacityBackpressureDropsAreHonestAndBounded() {
        store().use { owner ->
            for (i in 0..80) {
                now.set(2000L + i)
                assertEquals(OwnEventState.APPENDED,
                    owner.append("overflow-$i", OwnEventOrigin.APPLICATION, OwnEventKind.CRASH).state)
            }
            assertEquals(64, owner.pendingCount())
            val drops = owner.droppedCounters()
            assertEquals(17L, drops.first)
            val token = owner.openFakeSubscriber("owner", true)!!
            val page = owner.page(token, limit = 10_000)
            assertTrue(page.events.size <= 8)
            assertTrue(page.droppedOverflow >= 17)
            now.set(130_000L)
            assertEquals(0, owner.pendingCount())
            assertTrue(owner.droppedCounters().second >= 64L)
            assertEquals(OwnEventPageState.EMPTY, owner.page(token).state)
        }
    }

    @Test
    fun tN5C05ForeignCursorRevokedCallerAndOwnerContentionCannotRead() {
        store().use { owner ->
            owner.append("secret-1", OwnEventOrigin.APPLICATION, OwnEventKind.PERMISSION_REFUSED,
                OwnEventSensitivity.REDACTED_PRIVATE)
            assertNull(owner.openFakeSubscriber("other-app", true))
            assertNull(owner.openFakeSubscriber("this-app-owner", false))
            val legitimate = owner.openFakeSubscriber("this-app-owner", true)!!
            val response = owner.page(legitimate)
            assertEquals(OwnEventPageState.AVAILABLE, response.state)
            assertEquals(OwnEventPageState.DENIED,
                owner.page(legitimate, cursor = "forged-other-session").state)
            assertEquals(OwnEventPageState.DENIED, owner.page("other-caller").state)
            assertThrows(IllegalStateException::class.java) { store() }
            owner.stop()
            assertEquals(OwnEventPageState.STOPPED, owner.page(legitimate).state)
        }
        store().use { newOwner ->
            assertEquals(0, newOwner.pendingCount())
        }
    }

    @Test
    fun tN5C06StopClearsPrivateSpoolListenersAndNoSensitiveEventDataLeaks() {
        val owner = store()
        val token = owner.openFakeSubscriber("this-app-owner", true)!!
        owner.append("event-sensitive", OwnEventOrigin.FOREGROUND_SERVICE,
            OwnEventKind.CRASH, OwnEventSensitivity.REDACTED_PRIVATE)
        val page = owner.page(token)
        assertEquals(1, page.events.size)
        val serialized = page.encode().lowercase()
        for (private in listOf(
            "token", "nonce", "password", "secret", "filepath", "pid",
            "account", "stacktrace", "private_exception", "/users/",
        )) assertFalse(serialized.contains(private))
        owner.stop()
        assertEquals(0, owner.pendingCount())
        assertFalse(Files.exists(privateRoot.resolve("native-mcp-events").resolve("events.v1")))
        assertEquals(OwnEventPageState.STOPPED, owner.page(token).state)
        store().use { reopened ->
            assertEquals(0, reopened.pendingCount())
        }
    }

    @Test
    fun corruptJournalOrSymlinkedRootFailsClosedBeforeSubscriberAccess() {
        val origin = store()
        origin.append("journal-first", OwnEventOrigin.APPLICATION, OwnEventKind.CRASH)
        origin.simulateProcessDeath()
        val journal = privateRoot.resolve("native-mcp-events").resolve("events.v1")
        Files.writeString(journal, "N5C1|bad|corrupt-user-data\n")
        assertThrows(IllegalStateException::class.java) { store() }
        val anotherRoot = Files.createDirectory(privateRoot.resolve("other-root"))
        val symlink = privateRoot.resolve("linked-root")
        Files.createSymbolicLink(symlink, anotherRoot)
        assertThrows(IllegalStateException::class.java) {
            NativeDiagnosticEventStore(symlink, now::get)
        }
    }

    @Test
    fun crashRecoveryPurgesOrphanStagingAndDoesNotAcknowledgeDelivery() {
        val owner = store()
        val token = owner.openFakeSubscriber("owner", true)!!
        owner.append("pending-1", OwnEventOrigin.FOREGROUND_SERVICE, OwnEventKind.ANR)
        assertEquals(OwnEventPageState.AVAILABLE, owner.page(token).state)
        owner.simulateProcessDeath()
        val directory = privateRoot.resolve("native-mcp-events")
        val orphan = directory.resolve(".events-faulty.tmp")
        Files.writeString(orphan, "secret synthetic staged payload")
        now.set(1500)
        store().use { next ->
            assertFalse(Files.exists(orphan))
            assertEquals(1, next.pendingCount())
            assertEquals(OwnEventPageState.UNCERTAIN,
                next.page(next.openFakeSubscriber("owner", true)!!).state)
        }
        assertFalse(Files.exists(directory.resolve("events.v1")))
    }

    @Test
    fun concurrentUniqueEventsRemainOrderedAndQueueNeverExceedsLimit() {
        val monotonic = AtomicLong(5000)
        NativeDiagnosticEventStore(privateRoot, monotonic::incrementAndGet).use { owner ->
            val pool = Executors.newFixedThreadPool(8)
            val go = CountDownLatch(1)
            val ready = CountDownLatch(8)
            try {
                val replies = (0..7).map { i ->
                    pool.submit<OwnEventAppendResult> {
                        ready.countDown()
                        go.await(5, TimeUnit.SECONDS)
                        owner.append("event-concurrent-$i", OwnEventOrigin.ACTIVITY,
                            OwnEventKind.PERMISSION_REFUSED)
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                go.countDown()
                assertTrue(replies.map { it.get(8, TimeUnit.SECONDS) }
                    .all { it.state == OwnEventState.APPENDED })
                assertEquals(8, owner.pendingCount())
                val subscriber = owner.openFakeSubscriber("same-app", true)!!
                val first = owner.page(subscriber)
                assertEquals((1L..8L).toList(), first.events.map { it.id })
                assertEquals(OwnEventAckState.DENIED,
                    owner.acknowledge(subscriber, 9L))
            } finally {
                go.countDown()
                pool.shutdownNow()
            }
        }
    }

    @Test
    fun monotonicClockRollbackRefusesFabricatedEventOrSilentRetentionChange() {
        val owner = store()
        owner.append("first", OwnEventOrigin.ACTIVITY, OwnEventKind.STARTED)
        now.set(900)
        assertEquals(OwnEventState.UNAVAILABLE,
            owner.append("clock-reset", OwnEventOrigin.ACTIVITY, OwnEventKind.STARTED).state)
        assertEquals(0, owner.pendingCount())
        owner.stop()
    }
}

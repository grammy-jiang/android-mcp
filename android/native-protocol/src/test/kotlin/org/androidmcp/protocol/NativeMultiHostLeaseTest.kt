package org.androidmcp.protocol

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeMultiHostLeaseTest {
    private val now = AtomicLong(1000)
    private val install = "native-install-001"
    private val boot = "boot-epoch-001"
    private val app = "org.androidmcp.nativeapp"
    private val a = "host-alice"
    private val b = "host-bob"
    private fun lease(recovery: FakeLeaseRecovery? = null) =
        NativeMultiHostLease(install, boot, setOf(a, b), app, now::get, recovery)
    private fun request(host: String = a, fence: Long = 10) = FakeLeaseRequest(
        host, install, boot, app, "a".repeat(64), "req-$host-$fence", fence,
    )

    @Test
    fun tN6D01TwoVerifiedFakeHostsCompeteWithOnlyOneWinner() {
        val arbiter = lease()
        val pool = Executors.newFixedThreadPool(2)
        val go = CountDownLatch(1)
        val ready = CountDownLatch(2)
        try {
            val futures = listOf(request(a), request(b)).map {
                pool.submit<FakeLeaseReceipt> {
                    ready.countDown(); go.await(5, TimeUnit.SECONDS)
                    arbiter.acquire(it)
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            go.countDown()
            val results = futures.map { it.get(5, TimeUnit.SECONDS) }
            assertEquals(1, results.count { it.status == DualHostLeaseState.FAKE_HELD })
            assertEquals(1, results.count { it.status == DualHostLeaseState.BUSY })
            assertFalse(arbiter.realDeviceMutationAllowed())
        } finally { go.countDown(); pool.shutdownNow() }
    }

    @Test
    fun tN6D02WrongHostRenewalExpiryRepeatedReleaseAndStaleFenceDenied() {
        val arbiter = lease()
        val owner = request()
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.acquire(owner).status)
        assertEquals(DualHostLeaseState.DENIED, arbiter.renew(request(b)))
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.renew(owner))
        assertEquals(DualHostLeaseState.DENIED, arbiter.release(request(b)))
        assertEquals(DualHostLeaseState.RELEASED, arbiter.release(owner))
        assertEquals(DualHostLeaseState.ALREADY_RELEASED, arbiter.release(owner))
        assertEquals(DualHostLeaseState.STALE, arbiter.acquire(owner).status)
        now.set(15_000)
        val later = request(b, 11).copy(planDigest = "b".repeat(64))
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.acquire(later).status)
        now.set(26_000)
        assertEquals(DualHostLeaseState.EXPIRED, arbiter.renew(later))
        assertFalse(arbiter.realDeviceMutationAllowed())
    }

    @Test
    fun tN6D03UserStopsNativeFgsHostReceivesUncertainAndCannotTakeOver() {
        val arbiter = lease()
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.acquire(request()).status)
        arbiter.stop()
        val report = arbiter.recoverySnapshot()
        assertEquals(10, report.highWater)
        assertEquals(10, report.uncertainFence)
        assertEquals(DualHostLeaseState.UNAVAILABLE, arbiter.acquire(request(b, 11)).status)
        assertEquals(DualHostLeaseState.UNCERTAIN, arbiter.release(request()))
        assertFalse(arbiter.realDeviceMutationAllowed())
    }

    @Test
    fun tN6D04NativeCrashLeavesUncertainReceiptAndNoBlindReplayAfterRestart() {
        val first = lease()
        val approved = request(a)
        assertEquals(DualHostLeaseState.FAKE_HELD, first.acquire(approved).status)
        first.simulateProcessDeath()
        val snapshot = first.recoverySnapshot()
        assertEquals(10, snapshot.uncertainFence)
        val resumed = lease(snapshot)
        assertEquals(DualHostLeaseState.STALE, resumed.acquire(approved).status)
        assertEquals(DualHostLeaseState.FAKE_HELD,
            resumed.acquire(request(b, 11).copy(planDigest = "b".repeat(64))).status)
        assertFalse(resumed.realDeviceMutationAllowed())
    }

    @Test
    fun tN6D05FutureSchemaUnknownRequiredAndWrongNativeIdentityDenied() {
        val arbiter = lease()
        val invalid = listOf(
            request().copy(schemaVersion = 99),
            request().copy(unknownRequired = setOf("future_must_enforce")),
            request().copy(targetPackage = "com.other.private"),
            request().copy(nativeInstallation = "forged-native-install"),
            request().copy(bootEpoch = "wrong-boot-epoch"),
            request().copy(fakeSignatureVerified = false),
        )
        for (candidate in invalid) {
            assertFalse(arbiter.acquire(candidate).status == DualHostLeaseState.FAKE_HELD)
        }
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.acquire(request()).status)
    }

    @Test
    fun tN6D06FakeDualRuntimeCannotExecuteAdbOrExposeMutationTools() {
        val arbiter = lease()
        val result = arbiter.acquire(request())
        assertEquals(DualHostLeaseState.FAKE_HELD, result.status)
        val output = result.encode().lowercase()
        assertTrue(output.contains("synthetic_only"))
        assertTrue(output.contains("\"mutation_executed\":false"))
        for (forbidden in listOf("host-alice", "serial", "root", "adb",
            "private_key", "secret", "boot-epoch")) {
            assertFalse(output.contains(forbidden))
        }
        assertFalse(arbiter.realDeviceMutationAllowed())
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
    }
    @Test
    fun expiredActionWithHigherFenceAndSameDigestCannotBeReplayed() {
        val arbiter = lease()
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.acquire(request()).status)
        now.set(12_000)
        assertEquals(DualHostLeaseState.REPLAY, arbiter.acquire(
            request(b, 11).copy(requestId = "distinct-request"),
        ).status)
        assertEquals(DualHostLeaseState.FAKE_HELD, arbiter.acquire(
            request(b, 12).copy(planDigest = "c".repeat(64)),
        ).status)
        assertFalse(arbiter.realDeviceMutationAllowed())
    }

    @Test
    fun invalidPairingRecoveryAndClockRegressionLeaveNoDeviceMutation() {
        val first = lease()
        first.acquire(request())
        first.simulateProcessDeath()
        val broken = lease(first.recoverySnapshot().copy(bootEpoch = "different-boot"))
        assertEquals(DualHostLeaseState.PAIRING_REQUIRED,
            broken.acquire(request(b, 11).copy(planDigest = "b".repeat(64))).status)
        val current = lease()
        now.set(500)
        assertEquals(DualHostLeaseState.FAKE_HELD,
            current.acquire(request(b, 11).copy(planDigest = "c".repeat(64))).status)
        now.set(400)
        assertEquals(DualHostLeaseState.UNCERTAIN, current.renew(
            request(b, 11).copy(planDigest = "c".repeat(64))))
        assertEquals(DualHostLeaseState.UNAVAILABLE,
            current.acquire(request(a, 12).copy(planDigest = "d".repeat(64))).status)
        assertFalse(current.realDeviceMutationAllowed())
    }
}

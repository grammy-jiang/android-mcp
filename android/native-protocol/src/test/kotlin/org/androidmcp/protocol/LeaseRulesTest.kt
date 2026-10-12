package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class LeaseRulesTest {
    private val digest = "a".repeat(64)
    private val initial = LeaseSnapshot(
        deviceId = "tablet-01",
        pairingId = "paired-host-01",
        bootEpoch = "boot-0001",
        highFence = 5,
        lastObservedMs = 1_000L,
    )
    private val request = LeaseRequest(
        deviceId = initial.deviceId,
        pairingId = initial.pairingId,
        bootEpoch = initial.bootEpoch,
        ownerId = "trusted-host-01",
        planDigest = digest,
        requestId = "txn-1",
        fence = 6,
        ttlMs = 30_000L,
    )

    private fun accepted(decision: LeaseDecision): LeaseSnapshot {
        assertTrue(decision is LeaseDecision.Accepted, decision.toString())
        return (decision as LeaseDecision.Accepted).next
    }

    private fun rejected(decision: LeaseDecision, expected: LeaseRejectReason) {
        assertEquals(LeaseDecision.Rejected(expected), decision)
    }

    @Test
    fun uniqueAcquireAndExactReleasePreserveFence() {
        val held = accepted(LeaseRules.acquire(initial, request, 2_000))
        assertEquals(6, held.highFence)
        assertEquals("trusted-host-01", held.active?.ownerId)
        assertEquals(32_000L, held.active?.expiresAtMs)
        val idle = accepted(LeaseRules.release(held, "trusted-host-01", "txn-1", 6, 3_000))
        assertNull(idle.active)
        assertEquals(6, idle.highFence)
    }

    @Test
    fun simultaneousRequestCannotReplaceActiveLease() {
        val held = accepted(LeaseRules.acquire(initial, request, 2_000))
        rejected(
            LeaseRules.acquire(held, request.copy(fence = 7, requestId = "txn-2"), 2_001),
            LeaseRejectReason.DEVICE_BUSY,
        )
    }

    @Test
    fun expiredLeaseCanBeSupersededOnlyWithNewFencingToken() {
        val held = accepted(LeaseRules.acquire(initial, request.copy(ttlMs = 5_000), 2_000))
        rejected(
            LeaseRules.acquire(held, request.copy(fence = 6, requestId = "txn-2"), 7_000),
            LeaseRejectReason.STALE_FENCE,
        )
        val fresh = accepted(
            LeaseRules.acquire(held, request.copy(fence = 7, requestId = "txn-2"), 7_000)
        )
        assertEquals(7, fresh.highFence)
    }

    @Test
    fun releaseCannotBeForgedByWrongOwnerOrWrongToken() {
        val held = accepted(LeaseRules.acquire(initial, request, 2_000))
        rejected(
            LeaseRules.release(held, "other-host", "txn-1", 6, 3_000),
            LeaseRejectReason.NOT_OWNER,
        )
        rejected(
            LeaseRules.release(held, "trusted-host-01", "txn-2", 6, 3_000),
            LeaseRejectReason.NOT_OWNER,
        )
        rejected(
            LeaseRules.release(held, "trusted-host-01", "txn-1", 5, 3_000),
            LeaseRejectReason.NOT_OWNER,
        )
    }

    @Test
    fun cannotReleaseAnExpiredLease() {
        val held = accepted(LeaseRules.acquire(initial, request.copy(ttlMs = 2_000), 2_000))
        rejected(
            LeaseRules.release(held, "trusted-host-01", "txn-1", 6, 4_000),
            LeaseRejectReason.LEASE_EXPIRED,
        )
    }

    @Test
    fun wrongDevicePairingAndBootEpochFailClosed() {
        rejected(
            LeaseRules.acquire(initial, request.copy(deviceId = "tablet-02"), 2_000),
            LeaseRejectReason.WRONG_DEVICE,
        )
        rejected(
            LeaseRules.acquire(initial, request.copy(pairingId = "forged"), 2_000),
            LeaseRejectReason.WRONG_PAIRING,
        )
        rejected(
            LeaseRules.acquire(initial, request.copy(bootEpoch = "new-boot"), 2_000),
            LeaseRejectReason.WRONG_BOOT,
        )
    }

    @Test
    fun monotonicClockCannotMoveBackward() {
        rejected(LeaseRules.acquire(initial, request, 999), LeaseRejectReason.CLOCK_ROLLBACK)
        val held = accepted(LeaseRules.acquire(initial, request, 2_000))
        rejected(
            LeaseRules.release(held, "trusted-host-01", "txn-1", 6, 1_999),
            LeaseRejectReason.CLOCK_ROLLBACK,
        )
    }

    @Test
    fun persistFenceAcrossServiceRestartToPreventReplay() {
        val held = accepted(LeaseRules.acquire(initial, request, 2_000))
        val restored = held.copy(active = null)
        rejected(LeaseRules.acquire(restored, request, 3_000), LeaseRejectReason.STALE_FENCE)
    }

    @Test
    fun rejectsMalformedRequestsOrOverflow() {
        for (candidate in listOf(
            request.copy(fence = 0),
            request.copy(ttlMs = 0),
            request.copy(ttlMs = 300_001),
            request.copy(ownerId = "host; reboot"),
            request.copy(requestId = ""),
            request.copy(planDigest = "A".repeat(64)),
        )) {
            rejected(LeaseRules.acquire(initial, candidate, 2_000), LeaseRejectReason.INVALID_REQUEST)
        }
        rejected(
            LeaseRules.acquire(initial, request, Long.MAX_VALUE - 1),
            LeaseRejectReason.INVALID_REQUEST,
        )
    }
}

package org.androidmcp.lifecycle

import java.io.IOException
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

class NativeFenceStateTest {
    @TempDir lateinit var root: Path
    private val clock = AtomicLong(1_000L)
    private val install = "native-install-001"
    private val boot = "boot-epoch-001"
    private val host = "pinned-host-001"
    private fun state(beforeCommit: () -> Unit = {}) =
        NativeFenceState(root, install, boot, host, clock::get, beforeCommit)
    private fun grant(fence: Long = 10, digest: String = "a".repeat(64)) =
        SyntheticFenceRequest(install, boot, host, fence, digest,
            "nonce-$fence", 10_000L, true)

    @Test
    fun tN6C01FencingHighWaterPersistsAcrossForegroundRestart() {
        state().use { owner ->
            assertEquals(FenceStatus.SYNTHETIC_RECOGNIZED, owner.issue(grant()).status)
            assertEquals(10L, owner.highWater())
            assertFalse(owner.realMutationAllowed())
        }
        state().use { restarted ->
            assertEquals(10L, restarted.highWater())
            assertFalse(restarted.fakeLeaseActive())
            assertEquals(FenceStatus.STALE, restarted.issue(grant(10)).status)
            assertEquals(FenceStatus.SYNTHETIC_RECOGNIZED,
                restarted.issue(grant(11, "b".repeat(64))).status)
            assertEquals(11L, restarted.highWater())
            assertFalse(restarted.realMutationAllowed())
        }
    }

    @Test
    fun tN6C02StaleWrongHostDuplicateDigestAndNonceDeniedBeforeAnyMutation() {
        state().use { owner ->
            assertEquals(FenceStatus.SYNTHETIC_RECOGNIZED, owner.issue(grant()).status)
            val invalid = listOf(
                grant(10),
                grant(9),
                grant(12, "a".repeat(64)),
                grant(12, "b".repeat(64)).copy(nonce = "nonce-10"),
                grant(12, "b".repeat(64)).copy(hostIdentity = "other-host-001"),
                grant(12, "b".repeat(64)).copy(fakeHostProofAccepted = false),
            )
            for (bad in invalid) {
                assertFalse(owner.issue(bad).status == FenceStatus.SYNTHETIC_RECOGNIZED)
            }
            assertEquals(10L, owner.highWater())
            assertFalse(owner.realMutationAllowed())
        }
    }

    @Test
    fun tN6C03BootReinstallAndClockRollbackCannotResetPersistentFence() {
        state().use { owner ->
            assertEquals(FenceStatus.SYNTHETIC_RECOGNIZED, owner.issue(grant()).status)
        }
        NativeFenceState(root, install, "changed-boot-epoch", host, clock::get).use {
            assertEquals(FenceStatus.PAIRING_REQUIRED,
                it.issue(grant(15, "b".repeat(64))).status)
            assertEquals(10L, it.highWater())
        }
        NativeFenceState(root, "new-installation-001", boot, host, clock::get).use {
            assertEquals(FenceStatus.PAIRING_REQUIRED,
                it.issue(grant(100, "b".repeat(64)).copy(
                    nativeInstallation = "new-installation-001")).status)
            assertEquals(10L, it.highWater())
        }
        state().use { owner ->
            clock.set(900)
            assertEquals(FenceStatus.CLOCK_ROLLBACK,
                owner.issue(grant(20, "b".repeat(64))).status)
            assertEquals(10L, owner.highWater())
        }
    }

    @Test
    fun tN6C04CrashDuringPrivatePersistenceIsUncertainNotValidFence() {
        state {
            throw IOException("simulate full private filesystem no key material")
        }.use { failed ->
            val response = failed.issue(grant())
            assertEquals(FenceStatus.UNCERTAIN, response.status)
            assertNull(response.recordedHighWater)
            assertFalse(failed.realMutationAllowed())
            assertFalse(failed.fakeLeaseActive())
        }
        state().use { restarted ->
            assertEquals(0L, restarted.highWater())
            assertEquals(FenceStatus.SYNTHETIC_RECOGNIZED,
                restarted.issue(grant()).status)
        }
    }

    @Test
    fun tN6C05TwoConcurrentOwnersAndSameFenceGetOneAtomicWinner() {
        val first = state()
        try {
            assertThrows(IllegalStateException::class.java) { state() }
            val pool = Executors.newFixedThreadPool(8)
            val ready = CountDownLatch(8)
            val go = CountDownLatch(1)
            try {
                val futures = (0 until 8).map {
                    pool.submit<FenceReceipt> {
                        ready.countDown()
                        go.await(5, TimeUnit.SECONDS)
                        first.issue(grant())
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                go.countDown()
                val replies = futures.map { it.get(5, TimeUnit.SECONDS) }
                assertEquals(1, replies.count {
                    it.status == FenceStatus.SYNTHETIC_RECOGNIZED
                })
                assertEquals(10L, first.highWater())
            } finally { go.countDown(); pool.shutdownNow() }
        } finally { first.close() }
    }

    @Test
    fun tN6C06UnpairedMcpAndFakeLeaseCannotEnableRealDeviceMutation() {
        state().use { owner ->
            assertEquals(FenceStatus.SYNTHETIC_RECOGNIZED, owner.issue(grant()).status)
            assertFalse(owner.realMutationAllowed())
            val metadata = owner.issue(grant(11, "b".repeat(64))).encode().lowercase()
            for (sensitive in listOf("password", "secret", "nonce-", "private_key",
                "usb_serial", "root", "adb", "host-001")) {
                assertFalse(metadata.contains(sensitive))
            }
        }
    }

    @Test
    fun corruptedOrSymlinkedPrivateFenceRecordDeniedWithoutReset() {
        state().use { it.issue(grant()) }
        val file = root.resolve("native-mcp-fencing").resolve("fence.v1")
        Files.writeString(file, "fake fence 10000000000")
        assertThrows(IllegalStateException::class.java) { state() }
        val rootAlias = root.resolve("private-link")
        Files.createSymbolicLink(rootAlias, root)
        assertThrows(IllegalStateException::class.java) {
            NativeFenceState(rootAlias, install, boot, host, clock::get)
        }
    }
}

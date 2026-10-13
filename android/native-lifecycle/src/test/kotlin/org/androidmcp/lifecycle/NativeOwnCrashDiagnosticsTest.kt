package org.androidmcp.lifecycle

import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class NativeOwnCrashDiagnosticsTest {
    @TempDir lateinit var privateRoot: Path
    private val now = AtomicLong(1000L)
    private val own = "org.androidmcp.nativeapp"
    private fun reporter() = NativeOwnCrashDiagnostics(privateRoot, now::get)
    private fun sample(owner: NativeOwnCrashDiagnostics) = NativeCrashInput(
        own, 36, owner.processEpoch, "fake-crash-001", "1.0.2", 25_000,
        NativeCrashCode.OWN_EXCEPTION,
        "secret account=abc password=correct horse 1/Users/me/Library private@gmail.com",
    )

    @Test
    fun tN5A01OwnCrashAndAnrAreBoundedVersionedPrivateReports() {
        reporter().use { owner ->
            val crash = owner.record(sample(owner))
            assertEquals(NativeCrashState.RECORDED, crash.state)
            val receipt = crash.artifact!!
            assertEquals("application/json", receipt.mimeType)
            assertTrue(receipt.sizeBytes in 1..16_384)
            val data = owner.readPrivate(receipt.handle)!!.toString(Charsets.UTF_8)
            assertTrue(data.contains("\"schema_version\":1"))
            assertTrue(data.contains("\"app_version\":\"1.0.2\""))
            assertTrue(data.contains("\"uptime_ms\":25000"))
            assertTrue(data.contains("\"code\":\"own_exception\""))
            assertFalse(data.contains("password"))
            val anr = owner.record(sample(owner).copy(
                eventNonce = "fake-anr-002", code = NativeCrashCode.OWN_ANR,
            ))
            assertEquals(NativeCrashState.RECORDED, anr.state)
            assertEquals(2, owner.activeCount())
        }
    }

    @Test
    fun tN5A02OtherProcessCannotReadAnyGlobalCrashOrLogcat() {
        reporter().use { owner ->
            val forged = sample(owner).copy(packageName = "org.other.app")
            assertEquals(NativeCrashState.DENIED, owner.record(forged).state)
            assertNull(owner.record(forged).artifact)
            assertEquals(0, owner.activeCount())
            assertNull(owner.readPrivate("../data/tombstone"))
            assertNull(owner.readPrivate("/sdcard/other-app-crashes.txt"))
        }
    }

    @Test
    fun tN5A03ExceptionSecretsAndIdentifyingPathsNeverReachMetadataOrArtifact() {
        reporter().use { owner ->
            val result = owner.record(sample(owner))
            assertEquals(NativeCrashState.RECORDED, result.state)
            val privateBytes = owner.readPrivate(result.artifact!!.handle)!!
            val joined = privateBytes.toString(Charsets.UTF_8) + result.publicMetadataJson() +
                sample(owner).toString()
            for (secret in listOf(
                "correct horse", "private@gmail.com", "/Users/me/Library",
                "account=abc", "password=", "secret",
            )) assertFalse(joined.contains(secret))
            assertFalse(result.publicMetadataJson().contains(result.artifact.handle))
            assertTrue(result.publicMetadataJson().length < 1024)
        }
    }

    @Test
    fun tN5A04InterruptedFgServiceCrashReportCannotRetroactivelyBecomeSuccess() {
        val failing = NativeOwnCrashDiagnostics(privateRoot, now::get) { path, clock ->
            NativeArtifactStore(path, clock = clock, beforeCommit = {
                throw IOException("OEM secret from fake private service death")
            })
        }
        failing.use { owner ->
            val response = owner.record(sample(owner).copy(
                code = NativeCrashCode.OWN_FGS_FAILURE,
            ))
            assertEquals(NativeCrashState.INCOMPLETE, response.state)
            assertNull(response.artifact)
            assertEquals(0, owner.activeCount())
            assertFalse(response.publicMetadataJson().contains("OEM secret"))
        }
        reporter().use { next ->
            assertEquals(0, next.activeCount())
        }
    }

    @Test
    fun tN5A05ExpiryCloseAndRestartPurgePrivateDiagnosticBytes() {
        val handle: String
        reporter().use { owner ->
            handle = owner.record(sample(owner)).artifact!!.handle
            assertTrue(owner.readPrivate(handle) != null)
            now.set(121_001)
            assertNull(owner.readPrivate(handle))
            assertEquals(0, owner.activeCount())
        }
        val file = privateRoot.resolve("native-mcp-artifacts").resolve("fake-orphan-data")
        Files.writeString(file, "private orphan marker")
        reporter().use { restarted ->
            assertFalse(Files.exists(file))
            assertNull(restarted.readPrivate(handle))
            assertEquals(0, restarted.activeCount())
        }
    }

    @Test
    fun tN5A06UnauthenticatedOriginCannotDiscoverSensitiveAppDiagnostics() {
        reporter().use { owner ->
            assertEquals(NativeCrashState.DENIED,
                owner.record(sample(owner).copy(processEpoch = "other-epoch")).state)
            val result = owner.record(sample(owner))
            assertEquals(NativeCrashState.RECORDED, result.state)
            val encoded = result.publicMetadataJson()
            assertFalse(encoded.contains("privateExceptionMessage"))
            assertFalse(encoded.contains("artifactHandle"))
            assertFalse(encoded.contains("stacktrace"))
            assertFalse(encoded.contains("token"))
            assertTrue(encoded.contains("read_only"))
            assertTrue(encoded.contains("synthetic_only"))
        }
    }

    @Test
    fun concurrentDuplicateCrashReceiptsPublishOnceWithoutLeakingMessage() {
        reporter().use { owner ->
            val pool = Executors.newFixedThreadPool(8)
            val ready = CountDownLatch(8)
            val start = CountDownLatch(1)
            try {
                val jobs = (0 until 8).map {
                    pool.submit<NativeCrashResult> {
                        ready.countDown()
                        start.await(5, TimeUnit.SECONDS)
                        owner.record(sample(owner))
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                start.countDown()
                val outcomes = jobs.map { it.get(8, TimeUnit.SECONDS) }
                assertEquals(1, outcomes.count { it.state == NativeCrashState.RECORDED })
                assertEquals(7, outcomes.count { it.state == NativeCrashState.DUPLICATE })
                assertEquals(1, owner.activeCount())
                assertTrue(outcomes.all { !it.toString().contains("private@gmail.com") })
            } finally {
                start.countDown()
                pool.shutdownNow()
            }
        }
    }

    @Test
    fun capacityAndUntrustedVersionsCannotPublishSensitiveReports() {
        reporter().use { owner ->
            for (badVersion in listOf(
                "secret-token-private", "1.0.2\npassword=sensitive", "X".repeat(1000),
            )) {
                assertEquals(NativeCrashState.DENIED,
                    owner.record(sample(owner).copy(appVersion = badVersion)).state)
            }
            for (i in 0 until 4) {
                assertEquals(NativeCrashState.RECORDED,
                    owner.record(sample(owner).copy(eventNonce = "event-$i")).state)
            }
            assertEquals(4, owner.activeCount())
            assertEquals(NativeCrashState.BUSY,
                owner.record(sample(owner).copy(eventNonce = "excess")).state)
            assertEquals(4, owner.activeCount())
        }
    }

    @Test
    fun aSecondLiveStoreIsBusyAndCannotStealPriorProcessCrashArtifacts() {
        val first = reporter()
        try {
            val receipt = first.record(sample(first)).artifact!!
            reporter().use { competing ->
                assertNotEquals(first.processEpoch, competing.processEpoch)
                assertEquals(NativeCrashState.INCOMPLETE,
                    competing.record(sample(competing)).state)
                assertNull(competing.readPrivate(receipt.handle))
            }
            assertTrue(first.readPrivate(receipt.handle) != null)
            assertEquals(1, first.activeCount())
        } finally {
            first.close()
        }
        reporter().use { restarted ->
            assertEquals(0, restarted.activeCount())
        }
    }
}

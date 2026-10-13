package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

class NativeSyntheticRecordingTest {
    @TempDir lateinit var root: Path
    private val clock = AtomicLong(1_000)
    private fun recorder() = NativeSyntheticRecording(root, clock::get)
    private fun request() = SyntheticRecordingRequest(
        durationMs = 2_000, widthPx = 640, heightPx = 360,
        frameRate = 24, maxBytes = 1024 * 1024,
    )
    private fun permit(owner: NativeSyntheticRecording, api: Int = 36) =
        SyntheticRecordingPermit(
            apiLevel = api,
            processEpoch = owner.processEpoch,
            nonce = "recording-nonce-001",
            syntheticOnly = true,
            fakeCallerAuthenticated = true,
            fakeUiConsentGranted = true,
            callerForeground = true,
            mediaProjectionFgsTypeDeclared = true,
        )
    private fun fakeFragment(): ByteArray = byteArrayOf(
        0, 0, 0, 16, 102, 116, 121, 112, 105, 115, 111, 109, 0, 0, 0, 0,
    )
    private fun sha(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    @Test
    fun tN3C01FiniteSyntheticRecordingProducesBoundedPrivateArtifact() {
        recorder().use { owner ->
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.start(permit(owner), request()))
            assertTrue(owner.isRecording())
            val fragment = fakeFragment()
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.appendChunk(fragment))
            clock.set(2_000)
            val finished = owner.finish()
            assertEquals(SyntheticRecordingStatus.SIMULATED_ONLY, finished.status)
            val receipt = finished.artifact!!
            assertEquals("video/mp4", receipt.mimeType)
            assertEquals(fragment.size, receipt.sizeBytes)
            assertEquals(sha(fragment), receipt.sha256)
            assertTrue(receipt.expiresAtMs > receipt.createdAtMs)
            assertArrayEquals(fragment, Files.readAllBytes(
                root.resolve("native-mcp-artifacts").resolve(receipt.handle)))
            assertFalse(owner.isRecording())
            assertFalse(owner.realRecordingAllowed())
        }
    }

    @Test
    fun tN3C02FakeUnpairedStaleAndApi34_36TokenReuseAreDenied() {
        for (api in listOf(34, 36)) {
            recorder().use { owner ->
                val original = permit(owner, api)
                val invalid = listOf(
                    original.copy(fakeCallerAuthenticated = false),
                    original.copy(fakeUiConsentGranted = false),
                    original.copy(syntheticOnly = false),
                    original.copy(callerForeground = false),
                    original.copy(mediaProjectionFgsTypeDeclared = false),
                    original.copy(processEpoch = "not-original"),
                    original.copy(nonce = "bad\nnonce"),
                )
                for (candidate in invalid) {
                    assertFalse(owner.start(candidate, request()) ==
                        SyntheticRecordingStatus.STARTED_SYNTHETIC)
                    assertFalse(owner.isRecording())
                }
                assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                    owner.start(original, request()))
                assertEquals(SyntheticRecordingStatus.REPLAY_DENIED,
                    owner.start(original, request()))
                assertFalse(owner.realRecordingAllowed())
            }
        }
        val old = recorder()
        val permit = permit(old)
        old.close()
        recorder().use { fresh ->
            assertNotEquals(old.processEpoch, fresh.processEpoch)
            assertEquals(SyntheticRecordingStatus.STALE_DENIED,
                fresh.start(permit, request()))
        }
    }

    @Test
    fun tN3C03CancelUserStopProjectionStopAndProcessDeathReleaseBufferAndFile() {
        for (event in SyntheticRecordingStopEvent.entries) {
            recorder().use { owner ->
                assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                    owner.start(permit(owner), request()))
                owner.appendChunk(fakeFragment())
                owner.cancel(event)
                assertFalse(owner.isRecording())
                assertEquals(SyntheticRecordingStatus.CANCELLED, owner.finish().status)
                assertEquals(SyntheticRecordingStatus.STOPPED,
                    owner.appendChunk(fakeFragment()))
                assertEquals(SyntheticRecordingStatus.REPLAY_DENIED,
                    owner.start(permit(owner).copy(nonce = "new-nonce"), request()))
                assertEquals(0L, Files.list(root.resolve("native-mcp-artifacts"))
                    .use { it.filter { file -> !file.fileName.toString().startsWith(".") }.count() })
            }
        }
    }

    @Test
    fun tN3C04DuplicateAndConcurrentStartsNeverCreateOverlappingSession() {
        recorder().use { owner ->
            val workers = Executors.newFixedThreadPool(8)
            val ready = CountDownLatch(8)
            val start = CountDownLatch(1)
            try {
                val futures = (0 until 8).map { i ->
                    workers.submit<SyntheticRecordingStatus> {
                        ready.countDown()
                        start.await(5, TimeUnit.SECONDS)
                        owner.start(permit(owner).copy(nonce = "nonce-$i"), request())
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                start.countDown()
                val results = futures.map { it.get(8, TimeUnit.SECONDS) }
                assertEquals(1, results.count { it == SyntheticRecordingStatus.STARTED_SYNTHETIC })
                assertEquals(7, results.count { it == SyntheticRecordingStatus.BUSY })
                assertTrue(owner.isRecording())
            } finally {
                start.countDown()
                workers.shutdownNow()
            }
        }
    }

    @Test
    fun tN3C05OverflowDroppedFramesCodecFailureAndTimeoutNeverClaimCompleteVideo() {
        for (cause in listOf("oversize", "dropped", "codec", "timeout")) {
            clock.set(1_000)
            recorder().use { owner ->
                val request = request().copy(maxBytes = 64)
                assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                    owner.start(permit(owner), request))
                val state = when (cause) {
                    "oversize" -> owner.appendChunk(ByteArray(65) { 7 })
                    "dropped" -> owner.appendChunk(fakeFragment(), droppedFrames = 3)
                    "codec" -> owner.failCodec()
                    else -> {
                        clock.set(4_000)
                        owner.appendChunk(fakeFragment())
                    }
                }
                assertTrue(state in setOf(
                    SyntheticRecordingStatus.TOO_LARGE,
                    SyntheticRecordingStatus.PARTIAL,
                    SyntheticRecordingStatus.ERROR,
                    SyntheticRecordingStatus.TIMED_OUT,
                ))
                val result = owner.finish()
                assertFalse(result.status == SyntheticRecordingStatus.SIMULATED_ONLY)
                assertNull(result.artifact)
            }
        }
    }

    @Test
    fun tN3C06ShortTtlHashAndManifestCannotEnableRecording() {
        clock.set(1_000)
        recorder().use { owner ->
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.start(permit(owner), request()))
            owner.appendChunk(fakeFragment())
            val complete = owner.finish()
            val receipt = complete.artifact!!
            assertTrue(receipt.expiresAtMs - receipt.createdAtMs in 1..60_000)
            assertEquals(64, receipt.sha256.length)
            val wire = complete.metadataJson().lowercase()
            for (forbidden in listOf(
                "ftyp", "raw_frame", "screen_pixels", "data:video", "video/mp4",
                "filepath", "credential", "media_projection_token", "base64",
            )) assertFalse(wire.contains(forbidden))
            assertTrue(wire.contains("synthetic_only"))
            assertTrue(wire.length < 1024)
            assertFalse(owner.realRecordingAllowed())
        }
    }

    @Test
    fun monotonicClockRegressionCannotForgeSuccessfulFinish() {
        clock.set(10_000)
        recorder().use { owner ->
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.start(permit(owner), request()))
            clock.set(Long.MIN_VALUE)
            assertEquals(SyntheticRecordingStatus.TIMED_OUT,
                owner.appendChunk(fakeFragment()))
            assertNull(owner.finish().artifact)
            assertFalse(owner.realRecordingAllowed())
        }
    }

    @Test
    fun invalidDurationResolutionFrameRateAndBufferCannotOpenOwner() {
        val invalid = listOf(
            request().copy(durationMs = 0),
            request().copy(durationMs = 30_001),
            request().copy(widthPx = 0),
            request().copy(heightPx = 1081),
            request().copy(widthPx = 1921),
            request().copy(frameRate = 31),
            request().copy(frameRate = -1),
            request().copy(maxBytes = 8 * 1024 * 1024 + 1),
            request().copy(maxBytes = 0),
        )
        for (requested in invalid) {
            recorder().use { owner ->
                assertEquals(SyntheticRecordingStatus.DENIED,
                    owner.start(permit(owner), requested))
                assertFalse(owner.isRecording())
                assertFalse(Files.exists(root.resolve("native-mcp-artifacts")))
            }
        }
    }

    @Test
    fun deniedPrivateDirectoryAndInvalidFakeStreamNeverPublishArtifact() {
        val outside = Files.createDirectory(root.resolve("real-root"))
        val link = root.resolve("untrusted-symlink-root")
        Files.createSymbolicLink(link, outside)
        NativeSyntheticRecording(link, clock::get).use { owner ->
            assertEquals(SyntheticRecordingStatus.ERROR,
                owner.start(permit(owner), request()))
            assertFalse(owner.isRecording())
            assertNull(owner.finish().artifact)
            assertFalse(Files.exists(outside.resolve("native-mcp-artifacts")))
        }
        recorder().use { owner ->
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.start(permit(owner), request()))
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.appendChunk(byteArrayOf(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)))
            val malformed = owner.finish()
            assertEquals(SyntheticRecordingStatus.INVALID_STREAM, malformed.status)
            assertNull(malformed.artifact)
            assertFalse(owner.isRecording())
        }
    }

    @Test
    fun terminalFinishAndCloseCannotBeResumedOrReuseSyntheticPermit() {
        recorder().use { owner ->
            assertEquals(SyntheticRecordingStatus.STARTED_SYNTHETIC,
                owner.start(permit(owner), request()))
            owner.appendChunk(fakeFragment())
            val first = owner.finish()
            assertEquals(SyntheticRecordingStatus.SIMULATED_ONLY, first.status)
            assertEquals(SyntheticRecordingStatus.SIMULATED_ONLY, owner.finish().status)
            assertEquals(SyntheticRecordingStatus.REPLAY_DENIED,
                owner.start(permit(owner).copy(nonce = "fresh-other-nonce"), request()))
            assertFalse(owner.isRecording())
        }
    }
}

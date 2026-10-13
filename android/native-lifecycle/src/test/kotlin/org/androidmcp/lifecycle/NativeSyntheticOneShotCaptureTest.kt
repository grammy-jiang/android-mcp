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
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** N3.b tests do not touch any Android device or real projection token. */
class NativeSyntheticOneShotCaptureTest {
    @TempDir lateinit var privateRoot: Path

    private val onePixelPng: ByteArray = Base64.getDecoder().decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
    )
    private fun frame() = SyntheticFrame(1, 1, "image/png", onePixelPng.copyOf())
    private fun context(
        capture: NativeSyntheticOneShotCapture,
        api: Int = 36,
    ) = SyntheticCaptureContext(
        apiLevel = api,
        processEpoch = capture.processEpoch,
        nonce = "synthetic-nonce",
        syntheticOnly = true,
        fakeCallerAuthenticated = true,
        fakeUiConsentGranted = true,
        callerForeground = true,
        mediaProjectionFgsTypeDeclared = api < 34 || api == 34 || api == 36,
    )
    private fun expectedSha(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    @Test
    fun tN3B01OnlySyntheticAcceptedFrameBecomesPrivateHashedArtifact() {
        NativeSyntheticOneShotCapture(privateRoot).use { capture ->
            val data = frame()
            val result = capture.trySyntheticFrame(context(capture), data)
            assertEquals(SyntheticCaptureStatus.SIMULATED_ONLY, result.status)
            val receipt = result.artifact!!
            assertEquals("image/png", receipt.mimeType)
            assertEquals(data.bytes.size, receipt.sizeBytes)
            assertEquals(expectedSha(data.bytes), receipt.sha256)
            assertTrue(receipt.handle.matches(Regex("[A-Za-z0-9_-]{32}")))
            assertTrue(receipt.expiresAtMs > receipt.createdAtMs)
            val path = privateRoot.resolve("native-mcp-artifacts").resolve(receipt.handle)
            assertArrayEquals(data.bytes, Files.readAllBytes(path))
            assertFalse(result.publicMetadataJson().contains("iVBORw0KGgo"))
        }
    }

    @Test
    fun tN3B02AbsentRefusedLockedSecureAndUnpairedCannotCreateArtifact() {
        val cases = listOf(
            { c: SyntheticCaptureContext -> c.copy(fakeUiConsentGranted = false) },
            { c: SyntheticCaptureContext -> c.copy(fakeCallerAuthenticated = false) },
            { c: SyntheticCaptureContext -> c.copy(syntheticOnly = false) },
            { c: SyntheticCaptureContext -> c.copy(screenLocked = true) },
            { c: SyntheticCaptureContext -> c.copy(secureWindow = true) },
            { c: SyntheticCaptureContext -> c.copy(callerForeground = false) },
        )
        for (mutate in cases) {
            NativeSyntheticOneShotCapture(privateRoot).use { capture ->
                val response = capture.trySyntheticFrame(mutate(context(capture)), frame())
                assertFalse(response.status == SyntheticCaptureStatus.SIMULATED_ONLY)
                assertNull(response.artifact)
            }
        }
        assertFalse(Files.exists(privateRoot.resolve("captured-real-screen.png")))
    }

    @Test
    fun tN3B03DimensionsPixelBytesMimeAndTimeoutStrictlyBounded() {
        val bad = listOf(
            frame().copy(widthPx = 0),
            frame().copy(heightPx = 5000),
            frame().copy(widthPx = 2),
            frame().copy(mimeType = "text/plain"),
            frame().copy(bytes = byteArrayOf(1, 2, 3)),
            frame().copy(bytes = ByteArray(9 * 1024 * 1024) { 2 }),
        )
        for (frame in bad) {
            NativeSyntheticOneShotCapture(privateRoot).use { capture ->
                val response = capture.trySyntheticFrame(context(capture), frame)
                assertFalse(response.status == SyntheticCaptureStatus.SIMULATED_ONLY)
                assertNull(response.artifact)
            }
        }
        NativeSyntheticOneShotCapture(privateRoot).use { capture ->
            val overtime = capture.trySyntheticFrame(
                context(capture).copy(elapsedTimeMs = 10_000), frame(),
            )
            assertEquals(SyntheticCaptureStatus.TIMED_OUT, overtime.status)
            assertNull(overtime.artifact)
        }
    }

    @Test
    fun tN3B04Api30_33_34_36FakeTokenLifecycleNotRealProjection() {
        for (api in listOf(30, 33, 34, 36)) {
            NativeSyntheticOneShotCapture(privateRoot).use { capture ->
                val accepted = capture.trySyntheticFrame(context(capture, api), frame())
                assertEquals(SyntheticCaptureStatus.SIMULATED_ONLY, accepted.status)
                assertFalse(capture.captureRealIsAllowed())
                assertEquals(SyntheticCaptureStatus.REPLAY_DENIED,
                    capture.trySyntheticFrame(context(capture, api), frame()).status)
            }
        }
        NativeSyntheticOneShotCapture(privateRoot).use { capture ->
            assertEquals(SyntheticCaptureStatus.FGS_TYPE_REQUIRED,
                capture.trySyntheticFrame(context(capture).copy(
                    mediaProjectionFgsTypeDeclared = false
                ), frame()).status)
        }
        val old = NativeSyntheticOneShotCapture(privateRoot)
        val oldNonce = context(old)
        old.close()
        NativeSyntheticOneShotCapture(privateRoot).use { next ->
            assertNotEquals(old.processEpoch, next.processEpoch)
            assertEquals(SyntheticCaptureStatus.STALE_DENIED,
                next.trySyntheticFrame(oldNonce, frame()).status)
        }
    }

    @Test
    fun tN3B05StopRevocationAndProcessEndReleasePrivateHandleAndBuffers() {
        val handle: String
        val path: Path
        val capture = NativeSyntheticOneShotCapture(privateRoot)
        val accepted = capture.trySyntheticFrame(context(capture), frame())
        handle = accepted.artifact!!.handle
        path = privateRoot.resolve("native-mcp-artifacts").resolve(handle)
        assertTrue(Files.isRegularFile(path))
        capture.close() // simulates FGS Stop, projection callback or death cleanup
        assertFalse(Files.exists(path))
        assertEquals(SyntheticCaptureStatus.STOPPED,
            capture.trySyntheticFrame(context(capture), frame()).status)
        NativeSyntheticOneShotCapture(privateRoot).use { recovered ->
            assertFalse(Files.exists(path))
            assertFalse(recovered.captureRealIsAllowed())
        }
    }

    @Test
    fun tN3B06NoFrameBytesInResultLogOrMcpAndDefaultDisabled() {
        NativeSyntheticOneShotCapture(privateRoot).use { capture ->
            val bytes = onePixelPng.copyOf()
            val outcome = capture.trySyntheticFrame(context(capture), frame())
            val publicMetadata = outcome.publicMetadataJson().lowercase()
            assertTrue(publicMetadata.length < 1024)
            assertTrue(publicMetadata.contains("synthetic_only"))
            assertFalse(publicMetadata.contains(Base64.getEncoder().encodeToString(bytes)))
            assertFalse(publicMetadata.contains("data:image/"))
            assertFalse(publicMetadata.contains("screen_pixels"))
            assertFalse(publicMetadata.contains("secret"))
            assertFalse(capture.captureRealIsAllowed())
        }
    }

    @Test
    fun concurrentFakeFramesPublishAtMostOneOpaqueArtifact() {
        val pool = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val start = CountDownLatch(1)
        NativeSyntheticOneShotCapture(privateRoot).use { capture ->
            try {
                val jobs = (1..8).map {
                    pool.submit<SyntheticCaptureResult> {
                        ready.countDown()
                        start.await(5, TimeUnit.SECONDS)
                        capture.trySyntheticFrame(context(capture), frame())
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                start.countDown()
                val values = jobs.map { it.get(8, TimeUnit.SECONDS) }
                assertEquals(1, values.count { it.status == SyntheticCaptureStatus.SIMULATED_ONLY })
                assertEquals(7, values.count { it.status == SyntheticCaptureStatus.REPLAY_DENIED })
                val receipt = values.single { it.artifact != null }.artifact!!
                val path = privateRoot.resolve("native-mcp-artifacts").resolve(receipt.handle)
                assertTrue(Files.isRegularFile(path))
            } finally {
                start.countDown()
                pool.shutdownNow()
            }
        }
    }

    @Test
    fun privateDirectoryFailureNeverReturnsReceiptOrSensitiveError() {
        val missing = privateRoot.resolve("not-an-app-private-directory")
        NativeSyntheticOneShotCapture(missing).use { capture ->
            val result = capture.trySyntheticFrame(context(capture), frame())
            assertEquals(SyntheticCaptureStatus.ERROR, result.status)
            assertNull(result.artifact)
            assertFalse(result.publicMetadataJson().contains("not-an-app-private-directory"))
            assertFalse(capture.captureRealIsAllowed())
            assertEquals(SyntheticCaptureStatus.STOPPED,
                capture.trySyntheticFrame(context(capture), frame()).status)
        }
    }

    @Test
    fun malformedPngCrcTrailingDataAndEmbeddedMetadataNeverBecomeArtifacts() {
        val corruptedCRC = onePixelPng.copyOf().also {
            it[45] = (it[45].toInt() xor 0x40).toByte()
        }
        val trailing = onePixelPng + byteArrayOf(0, 0, 0, 0)
        val badIHDR = onePixelPng.copyOf().also { it[24] = 3 }
        for (payload in listOf(corruptedCRC, trailing, badIHDR)) {
            NativeSyntheticOneShotCapture(privateRoot).use { capture ->
                val response = capture.trySyntheticFrame(
                    context(capture), frame().copy(bytes = payload),
                )
                assertEquals(SyntheticCaptureStatus.INVALID_FRAME, response.status)
                assertNull(response.artifact)
                assertFalse(Files.exists(privateRoot.resolve("native-mcp-artifacts")
                    .resolve("captured.png")))
            }
        }
    }

    @Test
    fun concurrentCaptureRequestsUseAtMostOneSyntheticNonceAndArtifact() {
        NativeSyntheticOneShotCapture(privateRoot).use { capture ->
            val workers = Executors.newFixedThreadPool(6)
            val ready = CountDownLatch(6)
            val start = CountDownLatch(1)
            try {
                val futures = (0 until 6).map {
                    workers.submit<SyntheticCaptureResult> {
                        ready.countDown()
                        start.await(5, TimeUnit.SECONDS)
                        capture.trySyntheticFrame(context(capture), frame())
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                start.countDown()
                val responses = futures.map { it.get(8, TimeUnit.SECONDS) }
                assertEquals(1, responses.count { it.status == SyntheticCaptureStatus.SIMULATED_ONLY })
                assertEquals(5, responses.count { it.status == SyntheticCaptureStatus.REPLAY_DENIED })
                assertEquals(1, responses.count { it.artifact != null })
            } finally {
                start.countDown()
                workers.shutdownNow()
            }
        }
    }

    @Test
    fun failedPrivateFilesystemOwnershipNeverPublishesReceiptOrLeakedData() {
        val realRoot = Files.createDirectory(privateRoot.resolve("real-root"))
        val symlinkRoot = privateRoot.resolve("fake-root")
        Files.createSymbolicLink(symlinkRoot, realRoot)
        NativeSyntheticOneShotCapture(symlinkRoot).use { capture ->
            val failed = capture.trySyntheticFrame(context(capture), frame())
            assertEquals(SyntheticCaptureStatus.ERROR, failed.status)
            assertNull(failed.artifact)
            assertFalse(failed.publicMetadataJson().contains("fake-root"))
            assertFalse(capture.captureRealIsAllowed())
            assertEquals(
                SyntheticCaptureStatus.STOPPED,
                capture.trySyntheticFrame(context(capture).copy(nonce = "other"), frame()).status,
            )
        }
        assertFalse(Files.exists(realRoot.resolve("native-mcp-artifacts")))
    }
}

package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

class NativeArtifactStoreTest {
    @TempDir lateinit var privateRoot: Path

    private fun validHandle(seed: Char = 'A') = seed.toString().repeat(32)
    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    @Test
    fun tN0E01OpaqueHandleDigestMimeSizeAndBoundedExpiry() {
        val bytes = byteArrayOf(0, 1, 2, 0, 127, -1)
        NativeArtifactStore(privateRoot, clock = { 1000L }, ttlMs = 2000).use { store ->
            val receipt = store.create(bytes, "image/png")
            assertTrue(receipt.handle.matches(Regex("[A-Za-z0-9_-]{32}")))
            assertEquals("image/png", receipt.mimeType)
            assertEquals(bytes.size, receipt.sizeBytes)
            assertEquals(sha256(bytes), receipt.sha256)
            assertEquals(1000L, receipt.createdAtMs)
            assertEquals(3000L, receipt.expiresAtMs)
            assertArrayEquals(bytes, store.read(receipt.handle))
            assertEquals(1, store.activeCount())
        }
    }

    @Test
    fun tN0E02GuessedPathTraversalSymlinkAndOtherAppDataDenied() {
        val otherApp = Files.createTempFile(privateRoot.parent, "other-app-", ".private")
        Files.writeString(otherApp, "external-private-content")
        val link = privateRoot.resolveSibling(privateRoot.fileName.toString() + "-link")
        try {
            NativeArtifactStore(privateRoot).use { store ->
                val receipt = store.create(byteArrayOf(4, 5, 6), "application/octet-stream")
                assertNull(store.read("../" + otherApp.fileName))
                assertNull(store.read(otherApp.toUri().toString()))
                assertNull(store.read(receipt.handle + "/../unrelated"))
                assertNull(store.read("B".repeat(32)))
                assertFalse(store.remove("../" + otherApp.fileName))
                assertEquals("external-private-content", Files.readString(otherApp))
            }
            Files.createSymbolicLink(link, privateRoot)
            assertEquals(ArtifactFailureCode.INVALID_ROOT, assertThrows(ArtifactFailure::class.java) {
                NativeArtifactStore(link)
            }.code)
        } finally {
            Files.deleteIfExists(link)
            Files.deleteIfExists(otherApp)
        }
    }

    @Test
    fun tN0E03OversizeDiskFailureLeavesNoPublishedPartialOrSensitiveError() {
        NativeArtifactStore(privateRoot, maxArtifactBytes = 4).use { store ->
            val error = assertThrows(ArtifactFailure::class.java) {
                store.create(ByteArray(5) { 42 }, "image/png")
            }
            assertEquals(ArtifactFailureCode.TOO_LARGE, error.code)
            assertEquals(0, store.activeCount())
        }
        val message = "super-secret-capture-bytes-never-log"
        NativeArtifactStore(privateRoot, writeStaging = { _, _ ->
            throw IOException(message)
        }).use { store ->
            val error = assertThrows(ArtifactFailure::class.java) {
                store.create(message.toByteArray(), "image/png")
            }
            assertEquals(ArtifactFailureCode.IO_FAILURE, error.code)
            assertFalse(error.message.orEmpty().contains(message))
            assertEquals(0, store.activeCount())
        }
    }

    @Test
    fun tN0E04DuplicateHandleAndCrashDuringCommitCannotPublishPartial() {
        val knownHandle = validHandle()
        NativeArtifactStore(privateRoot, handleGenerator = { knownHandle }).use { store ->
            val original = byteArrayOf(1, 2, 3)
            val receipt = store.create(original, "image/png")
            assertEquals(knownHandle, receipt.handle)
            val collision = assertThrows(ArtifactFailure::class.java) {
                store.create(byteArrayOf(9, 9, 9), "image/png")
            }
            assertEquals(ArtifactFailureCode.INVALID_HANDLE, collision.code)
            assertArrayEquals(original, store.read(knownHandle))
        }
        NativeArtifactStore(
            privateRoot,
            handleGenerator = { validHandle('C') },
            beforeCommit = { throw IOException("simulated-crash-secret") },
        ).use { store ->
            val error = assertThrows(ArtifactFailure::class.java) {
                store.create(byteArrayOf(7, 8), "image/png")
            }
            assertEquals(ArtifactFailureCode.IO_FAILURE, error.code)
            assertEquals(0, store.activeCount())
            assertNull(store.read(validHandle('C')))
        }
    }

    @Test
    fun tN0E05ExpiryStopRestartPurgesAllArtifactsAndOrphans() {
        val now = AtomicLong(1000)
        lateinit var first: String
        NativeArtifactStore(privateRoot, clock = now::get, ttlMs = 1000).use { store ->
            first = store.create(byteArrayOf(1, 2), "image/png").handle
            assertEquals(1, store.activeCount())
            now.set(2001)
            assertNull(store.read(first))
            assertEquals(0, store.activeCount())
            store.create(byteArrayOf(5, 6), "image/png")
        }
        val owned = privateRoot.resolve("native-mcp-artifacts")
        assertTrue(Files.exists(owned))
        assertEquals(0, Files.list(owned).use { it.filter { path ->
            path.fileName.toString() != ".owner.lock"
        }.count() })
        Files.writeString(owned.resolve(".orphan-synthetic.part"), "discard on restart")
        NativeArtifactStore(privateRoot).use { recovered ->
            assertNull(recovered.read(first))
            assertFalse(Files.exists(owned.resolve(".orphan-synthetic.part")))
            assertEquals(0, recovered.activeCount())
        }
    }

    @Test
    fun tN0E06ReceiptsErrorsAndMetadataCannotLeakRawCapture() {
        val secret = "frame-token-do-not-expose-7dd7"
        NativeArtifactStore(privateRoot).use { store ->
            val receipt = store.create(secret.toByteArray(), "application/octet-stream")
            assertFalse(receipt.toString().contains(secret))
            assertFalse(receipt.toString().contains("privateRoot"))
            assertEquals(0, receipt.handle.count { it == '/' })
            assertEquals(64, receipt.sha256.length)
            assertEquals(secret, store.read(receipt.handle)!!.toString(Charsets.UTF_8))
            assertTrue(store.remove(receipt.handle))
            assertNull(store.read(receipt.handle))
        }
    }

    @Test
    fun competingWritersAndSecondStoreCannotOverwriteLiveArtifact() {
        val started = CountDownLatch(6)
        val go = CountDownLatch(1)
        val pool = Executors.newFixedThreadPool(6)
        NativeArtifactStore(privateRoot, maxEntries = 16).use { store ->
            try {
                val futures = (1..6).map { index ->
                    pool.submit<NativeArtifactReceipt> {
                        started.countDown()
                        go.await(5, TimeUnit.SECONDS)
                        store.create(byteArrayOf(index.toByte()), "image/png")
                    }
                }
                assertTrue(started.await(5, TimeUnit.SECONDS))
                go.countDown()
                val receipts = futures.map { it.get(5, TimeUnit.SECONDS) }
                assertEquals(6, receipts.distinctBy { it.handle }.size)
                assertEquals(6, store.activeCount())
                for ((i, receipt) in receipts.withIndex()) {
                    assertArrayEquals(byteArrayOf((i+1).toByte()), store.read(receipt.handle))
                }
                assertEquals(ArtifactFailureCode.BUSY, assertThrows(ArtifactFailure::class.java) {
                    NativeArtifactStore(privateRoot)
                }.code)
            } finally {
                go.countDown()
                pool.shutdownNow()
            }
        }
    }

    @Test
    fun attackerReplacesPublishedFileWithSymlinkThenCannotReadOtherAppData() {
        val outside = Files.createTempFile(privateRoot.parent, "outside-", ".secret")
        val secret = "other-app-private-record-999"
        Files.writeString(outside, secret)
        try {
            NativeArtifactStore(privateRoot).use { store ->
                val receipt = store.create(byteArrayOf(1, 2, 3), "image/png")
                val artifactPath = privateRoot.resolve("native-mcp-artifacts").resolve(receipt.handle)
                Files.delete(artifactPath)
                Files.createSymbolicLink(artifactPath, outside)
                assertNull(store.read(receipt.handle))
                assertEquals(secret, Files.readString(outside))
                assertEquals(0, store.activeCount())
                assertFalse(Files.exists(artifactPath, java.nio.file.LinkOption.NOFOLLOW_LINKS))
            }
        } finally {
            Files.deleteIfExists(outside)
        }
    }

    @Test
    fun shortWriteThatReturnsSuccessfullyCannotPublishIncompleteArtifact() {
        val secret = byteArrayOf(9, 8, 7, 6)
        NativeArtifactStore(
            privateRoot,
            writeStaging = { path, _ -> Files.write(path, byteArrayOf(9, 8)) },
        ).use { store ->
            val failure = assertThrows(ArtifactFailure::class.java) {
                store.create(secret, "image/png")
            }
            assertEquals(ArtifactFailureCode.IO_FAILURE, failure.code)
            assertEquals(0, store.activeCount())
        }
    }

    @Test
    fun sameLengthButAlteredStagingIsNotTrustedAsCommittedPayload() {
        NativeArtifactStore(
            privateRoot,
            writeStaging = { path, _ -> Files.write(path, byteArrayOf(4, 4, 4)) },
        ).use { store ->
            val failure = assertThrows(ArtifactFailure::class.java) {
                store.create(byteArrayOf(1, 2, 3), "image/png")
            }
            assertEquals(ArtifactFailureCode.IO_FAILURE, failure.code)
            assertEquals(0, store.activeCount())
        }
    }

    @Test
    fun itemAndTotalByteQuotasRefuseOverflowWithoutDeletingExisting() {
        NativeArtifactStore(
            privateRoot,
            maxArtifactBytes = 3,
            maxTotalBytes = 3,
            maxEntries = 1,
        ).use { store ->
            val good = store.create(byteArrayOf(1, 2, 3), "image/png")
            val failure = assertThrows(ArtifactFailure::class.java) {
                store.create(byteArrayOf(4), "image/png")
            }
            assertEquals(ArtifactFailureCode.CAPACITY, failure.code)
            assertArrayEquals(byteArrayOf(1, 2, 3), store.read(good.handle))
            assertEquals(1, store.activeCount())
        }
    }
}

package org.androidmcp.lifecycle

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import org.androidmcp.protocol.NativeSafGrantPolicy
import org.androidmcp.protocol.SafAccessMode
import org.androidmcp.protocol.SafGrantStatus
import org.androidmcp.protocol.SyntheticSafPickerResult
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class NativeSyntheticSafExportTest {
    @TempDir lateinit var privateRoot: Path
    private val time = AtomicLong(1000L)
    private val authority = "com.android.providers.downloads.documents"
    private val providerId = "synthetic-dummy-provider-1000"
    private val uri = "content://$authority/document/msf%3A100"
    private val content = "%PDF-1.7\nprivate-user-document-fixture".toByteArray()
    private val maxSize = 1024 * 1024

    private fun grants() = NativeSafGrantPolicy(setOf(authority), time::get)
    private fun fakePicker(policy: NativeSafGrantPolicy, api: Int = 36) =
        SyntheticSafPickerResult(
            apiLevel = api, processEpoch = policy.processEpoch,
            nonce = "fake-user-picked-document", launchedFromOwnPicker = true,
            action = NativeSafGrantPolicy.ACTION_OPEN_DOCUMENT,
            resultOk = true, contentUri = uri,
            requestedMode = SafAccessMode.READ,
            grantFlags = NativeSafGrantPolicy.FLAG_READ,
            osReadGranted = true, osWriteGranted = false,
            osPersistedRead = false, osPersistedWrite = false,
        )
    private fun exporter(policy: NativeSafGrantPolicy) = NativeSyntheticSafExporter(
        privateRoot, policy, authority, providerId, time::get,
    )
    private fun request(policy: NativeSafGrantPolicy, key: String = "request-1"): SafExportRequest {
        val result = policy.recognizeFake(fakePicker(policy))
        assertEquals(SafGrantStatus.SIMULATED_ONLY, result.status)
        return SafExportRequest(result.handle!!, uri, key)
    }
    private fun provider(
        bytes: ByteArray = content,
        providedUri: String = uri,
        providedAuthority: String = authority,
        providedId: String = providerId,
        mime: String = "application/pdf",
        declared: Long? = bytes.size.toLong(),
    ) = SyntheticDocumentProvider {
        SyntheticDocument(
            providedUri, providedAuthority, providedId, mime, declared,
            ByteArrayInputStream(bytes),
        )
    }
    private fun sha(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    @Test
    fun tN4D01SyntheticUserReadGrantCreatesPrivateHashedBoundedArtifact() {
        grants().use { policy ->
            exporter(policy).use { owner ->
                val planned = request(policy)
                val result = owner.export(planned, provider())
                assertEquals(SafExportStatus.SIMULATED_ONLY, result.status)
                val receipt = result.artifact!!
                assertEquals("application/pdf", receipt.mimeType)
                assertEquals(content.size, receipt.sizeBytes)
                assertEquals(sha(content), receipt.sha256)
                val path = privateRoot.resolve("native-mcp-artifacts").resolve(receipt.handle)
                assertArrayEquals(content, Files.readAllBytes(path))
                assertTrue(receipt.expiresAtMs > receipt.createdAtMs)
                assertFalse(owner.realContentResolverAccessAllowed())
            }
        }
    }

    @Test
    fun tN4D02WrongGrantRevokedUriProviderAliasOrIdentityFailClosed() {
        grants().use { policy ->
            val claim = request(policy)
            exporter(policy).use { owner ->
                val noGrant = owner.export(claim.copy(grantHandle = "A".repeat(32)), provider())
                assertEquals(SafExportStatus.DENIED, noGrant.status)
                val wrongUri = owner.export(
                    claim.copy(selectedUri = "content://$authority/document/msf%3A999"),
                    provider(),
                )
                assertEquals(SafExportStatus.DENIED, wrongUri.status)
                assertEquals(SafExportStatus.WRONG_PROVIDER,
                    owner.export(claim, provider(providedUri = "content://$authority/document/id")).status)
                assertEquals(SafExportStatus.WRONG_PROVIDER,
                    owner.export(claim, provider(providedAuthority = "com.evil.provider")).status)
                assertEquals(SafExportStatus.WRONG_PROVIDER,
                    owner.export(claim, provider(providedId = "other-provider-process")).status)
                assertTrue(policy.revoke(claim.grantHandle))
                assertEquals(SafExportStatus.REVOKED, owner.export(claim, provider()).status)
                assertFalse(owner.realContentResolverAccessAllowed())
                assertEquals(0, owner.activeArtifacts())
            }
        }
    }

    @Test
    fun tN4D03OversizeBrokenStreamsCancelDiskFailureNeverPublishPartial() {
        grants().use { policy ->
            val claim = request(policy)
            exporter(policy).use { owner ->
                val huge = ByteArray(maxSize + 1) { 7 }
                assertEquals(SafExportStatus.OVERSIZE,
                    owner.export(claim, provider(bytes = huge)).status)
                assertEquals(SafExportStatus.BROKEN_PROVIDER,
                    owner.export(claim, SyntheticDocumentProvider {
                        SyntheticDocument(uri, authority, providerId,
                            "application/pdf", content.size.toLong(),
                            object : InputStream() {
                                override fun read(): Int = throw IOException("private OEM provider secret")
                            })
                    }).status)
                assertEquals(0, owner.activeArtifacts())
                owner.cancel()
                assertEquals(SafExportStatus.CANCELLED, owner.export(claim, provider()).status)
            }
        }
        val fakeRoot = privateRoot.resolve("symlink-root")
        Files.createSymbolicLink(fakeRoot, privateRoot)
        grants().use { policy ->
            val claim = request(policy)
            NativeSyntheticSafExporter(fakeRoot, policy, authority, providerId, time::get).use { owner ->
                val result = owner.export(claim, provider())
                assertEquals(SafExportStatus.IO_FAILURE, result.status)
                assertNull(result.artifact)
            }
        }
    }

    @Test
    fun tN4D04DuplicateIdempotencyKeyGetsOneHandleNoStaleProcessRecovery() {
        grants().use { policy ->
            val claim = request(policy)
            val opens = AtomicInteger()
            exporter(policy).use { owner ->
                val source = SyntheticDocumentProvider {
                    opens.incrementAndGet()
                    provider().openSelected(uri)
                }
                val first = owner.export(claim, source)
                val second = owner.export(claim, source)
                assertEquals(SafExportStatus.SIMULATED_ONLY, first.status)
                assertEquals(first.artifact!!.handle, second.artifact!!.handle)
                assertEquals(1, opens.get())
                assertEquals(1, owner.activeArtifacts())
            }
            assertEquals(0L, Files.list(privateRoot.resolve("native-mcp-artifacts"))
                .use { it.filter { f -> !f.fileName.toString().startsWith(".") }.count() })
            grants().use { restarted ->
                assertNotEquals(policy.processEpoch, restarted.processEpoch)
                exporter(restarted).use { secondOwner ->
                    assertEquals(SafExportStatus.DENIED,
                        secondOwner.export(claim, provider()).status)
                }
            }
        }
    }

    @Test
    fun tN4D05FakeApi30_33_34_36ChoicesAndCancelledPickerHandled() {
        for (api in listOf(30, 33, 34, 36)) {
            time.set(1000)
            grants().use { policy ->
                val selection = policy.recognizeFake(fakePicker(policy, api))
                assertEquals(SafGrantStatus.SIMULATED_ONLY, selection.status)
                exporter(policy).use { owner ->
                    val result = owner.export(
                        SafExportRequest(selection.handle!!, uri, "api-$api"), provider(),
                    )
                    assertEquals(SafExportStatus.SIMULATED_ONLY, result.status)
                    assertFalse(owner.realContentResolverAccessAllowed())
                }
            }
            grants().use { policy ->
                val cancelled = policy.recognizeFake(fakePicker(policy, api).copy(resultOk = false))
                assertEquals(SafGrantStatus.CANCELLED, cancelled.status)
                exporter(policy).use { owner ->
                    assertEquals(SafExportStatus.DENIED,
                        owner.export(SafExportRequest("fake", uri, "cancelled"), provider()).status)
                }
            }
        }
    }

    @Test
    fun tN4D06RawDocumentUrisContentAccountPathsNotInPublicResponses() {
        grants().use { policy ->
            exporter(policy).use { owner ->
                val reply = owner.export(request(policy), provider())
                val output = reply.metadataJson().lowercase()
                for (forbidden in listOf(
                    "msf", "downloads", "content://", "private-user-document",
                    "password", "credential", "account", "/sdcard", "filepath",
                    "artifact_handle", "private_key",
                )) assertFalse(output.contains(forbidden))
                assertTrue(output.contains("synthetic_only"))
                assertTrue(output.contains("real_io_allowed"))
                assertFalse(owner.realContentResolverAccessAllowed())
            }
        }
    }

    @Test
    fun grantRevokedDuringProviderReadCannotPublishPrivateArtifact() {
        grants().use { policy ->
            val claim = request(policy)
            exporter(policy).use { owner ->
                val reading = SyntheticDocumentProvider { selected ->
                    assertEquals(uri, selected)
                    assertTrue(policy.revoke(claim.grantHandle))
                    provider().openSelected(uri)
                }
                val result = owner.export(claim, reading)
                assertEquals(SafExportStatus.REVOKED, result.status)
                assertNull(result.artifact)
                assertEquals(0, owner.activeArtifacts())
            }
        }
    }

    @Test
    fun cancelWhileProviderBlockedUnblocksWaiterAndPublishesNothing() {
        grants().use { policy ->
            val claim = request(policy)
            exporter(policy).use { owner ->
                val enteringRead = CountDownLatch(1)
                val releaseRead = CountDownLatch(1)
                val worker = Executors.newSingleThreadExecutor()
                try {
                    val blocking = SyntheticDocumentProvider {
                        SyntheticDocument(uri, authority, providerId, "application/pdf", null,
                            object : InputStream() {
                                override fun read(): Int {
                                    enteringRead.countDown()
                                    releaseRead.await(5, TimeUnit.SECONDS)
                                    throw IOException("provider cancelled")
                                }
                                override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
                                    read()
                                override fun close() {
                                    releaseRead.countDown()
                                }
                            })
                    }
                    val result = worker.submit<SafExportResult> { owner.export(claim, blocking) }
                    assertTrue(enteringRead.await(5, TimeUnit.SECONDS))
                    owner.cancel()
                    releaseRead.countDown()
                    assertEquals(SafExportStatus.CANCELLED,
                        result.get(5, TimeUnit.SECONDS).status)
                    assertEquals(0, owner.activeArtifacts())
                } finally {
                    releaseRead.countDown()
                    worker.shutdownNow()
                }
            }
        }
    }

    @Test
    fun guessedDuplicateIdempotencyKeyCannotSubstituteDifferentGrant() {
        grants().use { policy ->
            val firstClaim = request(policy)
            exporter(policy).use { owner ->
                val first = owner.export(firstClaim, provider())
                assertEquals(SafExportStatus.SIMULATED_ONLY, first.status)
                val secondGrant = policy.recognizeFake(fakePicker(policy).copy(
                    nonce = "another-user-selection",
                ))
                assertEquals(SafGrantStatus.SIMULATED_ONLY, secondGrant.status)
                val replacement = owner.export(
                    firstClaim.copy(grantHandle = secondGrant.handle!!),
                    provider(),
                )
                assertEquals(SafExportStatus.DENIED, replacement.status)
                assertNull(replacement.artifact)
                assertEquals(1, owner.activeArtifacts())
            }
        }
    }
}

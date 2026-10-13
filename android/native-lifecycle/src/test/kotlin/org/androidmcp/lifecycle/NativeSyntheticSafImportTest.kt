package org.androidmcp.lifecycle

import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
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

class NativeSyntheticSafImportTest {
    @TempDir lateinit var root: Path
    private val now = AtomicLong(1_000)
    private val authority = "com.android.providers.downloads.documents"
    private val provider = "private-synthetic-provider-id"
    private val uri = "content://$authority/document/msf%3A100"
    private val data = "synthetic-user-chosen-content".toByteArray()
    private fun sha(b: ByteArray) = MessageDigest.getInstance("SHA-256")
        .digest(b).joinToString("") { "%02x".format(it) }
    private fun grants() = NativeSafGrantPolicy(setOf(authority), now::get)
    private fun pick(owner: NativeSafGrantPolicy, api: Int = 36,
                     mode: SafAccessMode = SafAccessMode.WRITE, success: Boolean = true) =
        SyntheticSafPickerResult(
            api, owner.processEpoch, "synthetic-picked", true,
            NativeSafGrantPolicy.ACTION_OPEN_DOCUMENT, success, uri, mode,
            NativeSafGrantPolicy.FLAG_READ or NativeSafGrantPolicy.FLAG_WRITE,
            true, true, false, false,
        )
    private fun request(owner: NativeSafGrantPolicy, artifact: NativeArtifactReceipt,
                        api: Int = 36): SyntheticSafImportRequest {
        val grant = owner.recognizeFake(pick(owner, api))
        assertEquals(SafGrantStatus.SIMULATED_ONLY, grant.status)
        return SyntheticSafImportRequest(
            grant.handle!!, uri, artifact.handle, artifact.sha256,
            authority, provider, "import-key-001",
        )
    }
    private fun planner(store: NativeArtifactStore, policy: NativeSafGrantPolicy) =
        NativeSyntheticSafImportPlanner(store, policy, authority, provider)

    @Test
    fun tN4E01WriteGrantAndHashMatchingPrivateArtifactProduceAtomicPlanOnly() {
        NativeArtifactStore(root).use { store ->
            val artifact = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val request = request(policy, artifact)
                val plan = planner(store, policy).plan(request)
                assertEquals(SafImportState.PLAN_ONLY, plan.state)
                assertTrue(plan.planId!!.matches(Regex("[a-f0-9]{64}")))
                assertEquals(data.size, plan.bytesToWrite)
                assertEquals(sha(data), plan.sha256)
                assertFalse(plan.encode().contains("content://"))
                assertTrue(plan.encode().contains("\"executed\":false"))
                assertTrue(plan.encode().contains("\"atomic_write_guaranteed\":false"))
                assertArrayEquals(data, store.read(artifact.handle))
            }
        }
    }

    @Test
    fun tN4E02ReadOnlyRevokedForeignProviderOrWrongDestinationDenied() {
        NativeArtifactStore(root).use { store ->
            val artifact = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val input = request(policy, artifact)
                val planner = planner(store, policy)
                for (invalid in listOf(
                    input.copy(destinationUri = "content://$authority/document/msf%3A777"),
                    input.copy(destinationUri = "/sdcard/private.txt"),
                    input.copy(providerAuthority = "com.other.app"),
                    input.copy(providerProcessId = "forged-process"),
                    input.copy(fakeCallerAuthenticated = false),
                    input.copy(fakeUserApproved = false),
                )) {
                    val result = planner.plan(invalid)
                    assertFalse(result.state == SafImportState.PLAN_ONLY)
                    assertNull(result.planId)
                }
                assertTrue(policy.revoke(input.grantHandle))
                assertEquals(SafImportState.REVOKED, planner.plan(input).state)
            }
            grants().use { policy ->
                val readGrant = policy.recognizeFake(pick(policy, mode = SafAccessMode.READ))
                val attempt = SyntheticSafImportRequest(
                    readGrant.handle!!, uri, artifact.handle, artifact.sha256,
                    authority, provider, "read-only",
                )
                assertEquals(SafImportState.DENIED, planner(store, policy).plan(attempt).state)
            }
        }
    }

    @Test
    fun tN4E03OversizeTamperedArtifactAndProviderFailureCannotClaimAtomicWrite() {
        NativeArtifactStore(root).use { store ->
            val artifact = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val original = request(policy, artifact)
                val planner = planner(store, policy)
                assertEquals(SafImportState.HASH_MISMATCH,
                    planner.plan(original.copy(expectedSha256 = "b".repeat(64))).state)
                assertEquals(SafImportState.MISSING_ARTIFACT,
                    planner.plan(original.copy(artifactHandle = "c".repeat(32))).state)
                val path = root.resolve("native-mcp-artifacts").resolve(artifact.handle)
                Files.write(path, "untrusted-other-document".toByteArray())
                val outcome = planner.plan(original)
                assertEquals(SafImportState.MISSING_ARTIFACT, outcome.state)
                assertNull(outcome.planId)
                assertFalse(outcome.encode().contains("atomic_write_guaranteed\":true"))
            }
        }
    }

    @Test
    fun tN4E04DuplicateRequestStablePlanIdButNeverSilentOverwrite() {
        NativeArtifactStore(root).use { store ->
            val source = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val request = request(policy, source)
                val planner = planner(store, policy)
                val original = planner.plan(request)
                val duplicate = planner.plan(request)
                assertEquals(SafImportState.PLAN_ONLY, original.state)
                assertEquals(original.planId, duplicate.planId)
                assertEquals(SafImportState.DENIED, planner.plan(
                    request.copy(idempotencyKey = "new-unapproved-request"),
                ).state)
                assertFalse(planner.realDocumentWriteAllowed())
                assertTrue(planner.cancel() == SafImportState.CANCELLED)
                assertEquals(SafImportState.CANCELLED, planner.plan(request).state)
            }
        }
    }

    @Test
    fun tN4E05FourApiPickerCancelledAndProcessDeathDistinctBeforeAfterDispatch() {
        for (api in listOf(30, 33, 34, 36)) {
            NativeArtifactStore(root).use { store ->
                val source = store.create(data, "application/octet-stream")
                grants().use { policy ->
                    val request = request(policy, source, api)
                    val planner = planner(store, policy)
                    assertEquals(SafImportState.PLAN_ONLY, planner.plan(request).state)
                    planner.markFakeDispatchStarted()
                    assertEquals(SafImportState.UNCERTAIN, planner.cancel())
                    assertEquals(SafImportState.UNCERTAIN, planner.plan(request).state)
                    assertFalse(planner.realDocumentWriteAllowed())
                }
                grants().use { policy ->
                    assertEquals(SafGrantStatus.CANCELLED,
                        policy.recognizeFake(pick(policy, api, success = false)).status)
                }
            }
        }
    }

    @Test
    fun fakeDispatchMarkerRechecksGrantAfterAPlanWasCreated() {
        NativeArtifactStore(root).use { store ->
            val artifact = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val selected = request(policy, artifact)
                val planner = planner(store, policy)
                assertEquals(SafImportState.PLAN_ONLY, planner.plan(selected).state)
                assertTrue(policy.revoke(selected.grantHandle))
                assertEquals(SafImportState.REVOKED, planner.markFakeDispatchStarted())
                assertEquals(SafImportState.CANCELLED, planner.cancel())
                assertFalse(planner.realDocumentWriteAllowed())
            }
        }
    }

    @Test
    fun tN4E06DefaultMcpNeverWritesSystemPathOrLeaksDocumentData() {
        NativeArtifactStore(root).use { store ->
            val source = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val request = request(policy, source)
                val planner = planner(store, policy)
                val plan = planner.plan(request)
                val encoded = plan.encode().lowercase()
                for (forbidden in listOf(
                    "content://", "msf", "downloads", "/sdcard",
                    "synthetic-user-chosen-content", "account", "private_key",
                    "filepath", "content_resolver", "token",
                )) assertFalse(encoded.contains(forbidden))
                assertFalse(planner.realDocumentWriteAllowed())
                assertTrue(encoded.toByteArray().size < 2048)
            }
        }
    }

    @Test
    fun concurrentDuplicatesHaveOneStablePlanAndNoWriteSideEffect() {
        NativeArtifactStore(root).use { store ->
            val source = store.create(data, "application/octet-stream")
            grants().use { policy ->
                val selected = request(policy, source)
                val planner = planner(store, policy)
                val executor = Executors.newFixedThreadPool(6)
                val ready = CountDownLatch(6)
                val start = CountDownLatch(1)
                try {
                    val futures = (1..6).map {
                        executor.submit<SyntheticSafImportPlan> {
                            ready.countDown()
                            start.await(5, TimeUnit.SECONDS)
                            planner.plan(selected)
                        }
                    }
                    assertTrue(ready.await(5, TimeUnit.SECONDS))
                    start.countDown()
                    val results = futures.map { it.get(5, TimeUnit.SECONDS) }
                    assertEquals(1, results.map { it.planId }.distinct().size)
                    assertTrue(results.all { it.state == SafImportState.PLAN_ONLY })
                    assertFalse(planner.realDocumentWriteAllowed())
                    assertArrayEquals(data, store.read(source.handle))
                } finally {
                    start.countDown()
                    executor.shutdownNow()
                }
            }
        }
    }

    @Test
    fun symlinkedOrTruncatedPrivateArtifactCannotProduceImportPlan() {
        val other = Files.createTempFile(root.parent, "other-provider-", ".doc")
        Files.write(other, "foreign-private-data".toByteArray())
        try {
            NativeArtifactStore(root).use { store ->
                val stored = store.create(data, "application/octet-stream")
                grants().use { policy ->
                    val selected = request(policy, stored)
                    val planner = planner(store, policy)
                    val file = root.resolve("native-mcp-artifacts").resolve(stored.handle)
                    Files.delete(file)
                    Files.createSymbolicLink(file, other)
                    val result = planner.plan(selected)
                    assertEquals(SafImportState.MISSING_ARTIFACT, result.state)
                    assertNull(result.planId)
                    assertEquals("foreign-private-data", Files.readString(other))
                    assertFalse(planner.realDocumentWriteAllowed())
                }
            }
        } finally {
            Files.deleteIfExists(other)
        }
    }

    @Test
    fun syntheticProcessRestartAndRevokedUriHaveNoDurableWriterAuthority() {
        val firstPolicy = grants()
        val handle: String
        NativeArtifactStore(root).use { store ->
            val artifact = store.create(data, "application/octet-stream")
            val selected = request(firstPolicy, artifact)
            handle = selected.grantHandle
            val firstPlanner = planner(store, firstPolicy)
            assertEquals(SafImportState.PLAN_ONLY, firstPlanner.plan(selected).state)
            firstPolicy.revoke(handle)
            assertEquals(SafImportState.REVOKED, firstPlanner.plan(selected).state)
        }
        firstPolicy.close()
        grants().use { nextPolicy ->
            NativeArtifactStore(root).use { restartedStore ->
                val nextPlanner = planner(restartedStore, nextPolicy)
                assertEquals(SafImportState.DENIED,
                    nextPlanner.plan(SyntheticSafImportRequest(
                        handle, uri, "A".repeat(32), sha(data),
                        authority, provider, "restart",
                    )).state)
                assertFalse(nextPlanner.realDocumentWriteAllowed())
            }
        }
    }
}

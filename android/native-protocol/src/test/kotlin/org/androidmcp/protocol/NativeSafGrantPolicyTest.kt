package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class NativeSafGrantPolicyTest {
    private val clock = AtomicLong(1000L)
    private val trustedAuthority = "com.android.providers.downloads.documents"
    private val doc = "content://$trustedAuthority/document/msf%3A100"
    private fun policy() = NativeSafGrantPolicy(setOf(trustedAuthority), clock::get)
    private fun result(owner: NativeSafGrantPolicy, mode: SafAccessMode = SafAccessMode.READ) =
        SyntheticSafPickerResult(
            apiLevel = 36, processEpoch = owner.processEpoch,
            nonce = "synthetic-picked-nonce", launchedFromOwnPicker = true,
            action = "android.intent.action.OPEN_DOCUMENT", resultOk = true,
            contentUri = doc, requestedMode = mode,
            grantFlags = 1 or 2 or 64,
            osReadGranted = true, osWriteGranted = true,
            osPersistedRead = false, osPersistedWrite = false,
        )

    @Test
    fun tN4C01OwnPickerAndOsReadProofYieldOpaqueScopedReadHandleOnly() {
        policy().use { owner ->
            val item = owner.recognizeFake(result(owner))
            assertEquals(SafGrantStatus.SIMULATED_ONLY, item.status)
            assertTrue(item.handle!!.matches(Regex("[A-Za-z0-9_-]{32}")))
            assertEquals(SafAccessMode.READ, item.mode)
            assertFalse(item.persisted)
            assertEquals(61000L, item.expiresAtMs)
            assertEquals(SafGrantStatus.SIMULATED_ONLY, owner.check(item.handle, SafAccessMode.READ))
            assertEquals(SafGrantStatus.DENIED, owner.check(item.handle, SafAccessMode.WRITE))
            assertEquals(1, owner.activeCount())
            val wire = Json.parseToJsonElement(item.metadataJson()).jsonObject
            assertEquals("simulated_only", wire.getValue("status").jsonPrimitive.content)
            assertEquals("false", wire.getValue("real_io_allowed").jsonPrimitive.content)
            assertFalse(item.metadataJson().contains(trustedAuthority))
            assertFalse(item.metadataJson().contains("msf"))
            assertFalse(owner.realDocumentIoAllowed())
        }
    }

    @Test
    fun tN4C02ForgedUrisAuthoritiesExpiredOrRevokedGrantAreDenied() {
        val forged = listOf(
            "file:///sdcard/private.txt", "/sdcard/DCIM/Pictures",
            "content://com.other.app/document/secret",
            "content://$trustedAuthority/document/%2e%2e%2fprivate",
            "content://$trustedAuthority/document/id?token=secret",
            "content://$trustedAuthority/document/id#fragment",
            "content://user:pass@$trustedAuthority/document/42",
            "content://$trustedAuthority/document/../../private",
            "content://$trustedAuthority/document/",
            "content://$trustedAuthority/tree/123",
            "content://$trustedAuthority/document/%252e%252e%252fprivate",
            "https://$trustedAuthority/document/abc",
        )
        policy().use { owner ->
            for ((n, uri) in forged.withIndex()) {
                val denied = owner.recognizeFake(
                    result(owner).copy(nonce = "forged-$n", contentUri = uri),
                )
                assertEquals(SafGrantStatus.DENIED, denied.status)
                assertNull(denied.handle)
            }
            val granted = owner.recognizeFake(result(owner))
            val handle = granted.handle!!
            assertTrue(owner.revoke(handle))
            assertEquals(SafGrantStatus.REVOKED, owner.check(handle, SafAccessMode.READ))
            assertFalse(owner.realDocumentIoAllowed())
        }
        clock.set(1000)
        policy().use { owner ->
            val handle = owner.recognizeFake(result(owner)).handle!!
            clock.set(61001)
            assertEquals(SafGrantStatus.EXPIRED, owner.check(handle, SafAccessMode.READ))
            assertEquals(0, owner.activeCount())
        }
    }

    @Test
    fun tN4C03ReadWriteAndPersistableOneTimeAreNotInterchangeable() {
        policy().use { owner ->
            val read = owner.recognizeFake(result(owner).copy(
                grantFlags = 1, osWriteGranted = false,
            ))
            assertEquals(SafGrantStatus.SIMULATED_ONLY, read.status)
            assertFalse(read.persisted)
            assertEquals(SafGrantStatus.DENIED,
                owner.check(read.handle!!, SafAccessMode.WRITE))
            assertEquals(SafGrantStatus.DENIED, owner.recognizeFake(
                result(owner, SafAccessMode.WRITE).copy(
                    nonce = "write-without-os-grant",
                    grantFlags = 1, osWriteGranted = false,
                )
            ).status)
            val write = owner.recognizeFake(
                result(owner, SafAccessMode.WRITE).copy(nonce = "write-scoped-grant")
            )
            assertEquals(SafAccessMode.WRITE, write.mode)
            assertEquals(SafGrantStatus.SIMULATED_ONLY,
                owner.check(write.handle!!, SafAccessMode.WRITE))
            assertEquals(SafGrantStatus.DENIED,
                owner.check(write.handle, SafAccessMode.READ))
            val persistable = owner.recognizeFake(
                result(owner).copy(
                    nonce = "already-persisted",
                    grantFlags = 1 or 64, osPersistedRead = true,
                )
            )
            assertTrue(persistable.persisted)
            assertEquals(SafGrantStatus.DENIED, owner.recognizeFake(
                result(owner).copy(
                    nonce = "claimed-persisted-only",
                    grantFlags = 1 or 64, osReadGranted = false, osPersistedRead = true,
                )
            ).status)
        }
    }

    @Test
    fun tN4C04CancelledBadResultProviderErrorAndWrongPickerAreTypedDenied() {
        policy().use { owner ->
            val cancelled = owner.recognizeFake(result(owner).copy(resultOk = false))
            assertEquals(SafGrantStatus.CANCELLED, cancelled.status)
            assertNull(cancelled.handle)
            for (bad in listOf(
                result(owner).copy(launchedFromOwnPicker = false),
                result(owner).copy(action = "android.intent.action.VIEW"),
                result(owner).copy(userScope = "work_profile"),
                result(owner).copy(contentUri = null),
                result(owner).copy(osReadGranted = null),
                result(owner).copy(osReadGranted = false),
            )) {
                assertFalse(owner.recognizeFake(bad).status == SafGrantStatus.SIMULATED_ONLY)
            }
            assertEquals(0, owner.activeCount())
            assertFalse(owner.realDocumentIoAllowed())
        }
    }

    @Test
    fun tN4C05AndroidApi30_33_34_36AndRestartEpochHaveNoBroadStorageGrant() {
        for (api in listOf(30, 33, 34, 36)) {
            clock.set(1000)
            policy().use { owner ->
                val chosen = owner.recognizeFake(result(owner).copy(apiLevel = api))
                assertEquals(SafGrantStatus.SIMULATED_ONLY, chosen.status)
                assertFalse(owner.realDocumentIoAllowed())
            }
        }
        policy().use { owner ->
            assertEquals(SafGrantStatus.UNSUPPORTED,
                owner.recognizeFake(result(owner).copy(apiLevel = 29)).status)
            val old = owner.recognizeFake(result(owner))
            val other = policy()
            other.use { next ->
                assertNotEquals(owner.processEpoch, next.processEpoch)
                assertEquals(SafGrantStatus.STALE,
                    next.recognizeFake(result(owner)).status)
                assertEquals(SafGrantStatus.DENIED,
                    next.check(old.handle!!, SafAccessMode.READ))
            }
        }
    }

    @Test
    fun tN4C06UriStringNeverGrantsOtherAppStorageOrPublicToolAccess() {
        policy().use { owner ->
            val granted = owner.recognizeFake(result(owner))
            assertEquals(SafGrantStatus.SIMULATED_ONLY, granted.status)
            assertEquals(SafGrantStatus.REPLAY_DENIED, owner.recognizeFake(result(owner)).status)
            assertEquals(SafGrantStatus.DENIED,
                owner.check(doc, SafAccessMode.READ))
            assertEquals(SafGrantStatus.DENIED,
                owner.check("../data/system", SafAccessMode.WRITE))
            assertFalse(owner.realDocumentIoAllowed())
            assertFalse(granted.metadataJson().contains("content://"))
        }
        val live = NativeToolProfiles().liveTools(true).map { it.name }
        assertEquals(listOf("device_status"), live)
        assertFalse(NativeLocalStatus.encode().contains("document_uri"))
    }

    @Test
    fun concurrentlyClaimedFakePickerNonceProducesOnlyOneHandle() {
        clock.set(1000)
        policy().use { owner ->
            val pool = Executors.newFixedThreadPool(8)
            val ready = CountDownLatch(8)
            val go = CountDownLatch(1)
            try {
                val tasks = (0 until 8).map {
                    pool.submit<SafGrantReceipt> {
                        ready.countDown()
                        go.await(5, TimeUnit.SECONDS)
                        owner.recognizeFake(result(owner))
                    }
                }
                assertTrue(ready.await(5, TimeUnit.SECONDS))
                go.countDown()
                val replies = tasks.map { it.get(5, TimeUnit.SECONDS) }
                assertEquals(1, replies.count { it.status == SafGrantStatus.SIMULATED_ONLY })
                assertEquals(7, replies.count { it.status == SafGrantStatus.REPLAY_DENIED })
                assertEquals(1, owner.activeCount())
                assertFalse(owner.realDocumentIoAllowed())
            } finally {
                go.countDown()
                pool.shutdownNow()
            }
        }
    }

    @Test
    fun providerAndNonceLimitsNeverPermitUnboundedFakeGrants() {
        clock.set(1000)
        policy().use { owner ->
            for (index in 0 until 8) {
                val grant = owner.recognizeFake(
                    result(owner).copy(nonce = "grant-$index"),
                )
                assertEquals(SafGrantStatus.SIMULATED_ONLY, grant.status)
            }
            assertEquals(SafGrantStatus.UNAVAILABLE, owner.recognizeFake(
                result(owner).copy(nonce = "capacity-extra"),
            ).status)
            assertEquals(8, owner.activeCount())
            assertEquals(SafGrantStatus.DENIED, owner.check(doc, SafAccessMode.READ))
            owner.close()
            assertEquals(0, owner.activeCount())
            assertEquals(SafGrantStatus.REVOKED,
                owner.recognizeFake(result(owner)).status)
        }
    }

    @Test
    fun diagnosticStringNeverPrintsUserUriAndExistingGrantCannotCrossProcess() {
        clock.set(1000)
        val first = policy()
        val proof = result(first)
        assertFalse(proof.toString().contains("msf"))
        assertFalse(proof.toString().contains("downloads"))
        val handle = first.recognizeFake(proof).handle!!
        assertFalse(first.realDocumentIoAllowed())
        first.close()
        policy().use { next ->
            assertNotEquals(first.processEpoch, next.processEpoch)
            assertEquals(SafGrantStatus.DENIED,
                next.check(handle, SafAccessMode.READ))
        }
    }
}

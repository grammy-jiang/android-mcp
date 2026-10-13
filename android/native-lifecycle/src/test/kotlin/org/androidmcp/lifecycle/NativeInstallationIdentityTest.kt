package org.androidmcp.lifecycle

import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class NativeInstallationIdentityTest {
    @TempDir lateinit var privateRoot: Path
    private val now = AtomicLong(1000L)
    private class FakeKeystore : NativeInstallationSigningProvider {
        val keys = ConcurrentHashMap<String, KeyPair>()
        var lastAlias: String? = null
        override fun createKey(alias: String): ByteArray {
            val factory = KeyPairGenerator.getInstance("EC")
            factory.initialize(ECGenParameterSpec("secp256r1"))
            val pair = factory.generateKeyPair()
            check(keys.putIfAbsent(alias, pair) == null)
            lastAlias = alias
            return pair.public.encoded
        }
        override fun publicKey(alias: String): ByteArray? = keys[alias]?.public?.encoded
        override fun sign(alias: String, challenge: ByteArray): ByteArray? =
            keys[alias]?.private?.let {
                Signature.getInstance("SHA256withECDSA").run {
                    initSign(it); update(challenge); sign()
                }
            }
        override fun deleteKey(alias: String) { keys.remove(alias) }
    }
    private val backend = FakeKeystore()
    private fun store() = NativeInstallationIdentity(privateRoot, backend, now::get)

    @Test
    fun tN6A01FreshPrivateInstallIdentityAndVerificationKeyHaveNoDeviceId() {
        store().use { owner ->
            val public = owner.publicIdentity()
            assertTrue(public.installationId.matches(Regex("[a-f0-9-]{36}")))
            assertTrue(public.verificationKeySha256.matches(Regex("[a-f0-9]{64}")))
            assertTrue(public.publicKeyBase64.length in 60..300)
            assertNotEquals(public.installationId, owner.processEpoch)
            val status = public.encode().lowercase()
            assertTrue(status.contains("verification_key_sha256"))
            for (secret in listOf("android_serial", "imei", "mac_address",
                "android_id", "private_key", "pkcs8", "password", "keystore_alias")) {
                assertFalse(status.contains(secret))
            }
        }
    }

    @Test
    fun tN6A02SimulatedAppDataClearRotatesInstallAndInvalidatesHostBinding() {
        val first = store().use { it.publicIdentity() }
        val state = privateRoot.resolve("native-mcp-install-identity").resolve("installation.v1")
        assertTrue(Files.isRegularFile(state))
        Files.delete(state) // simulated disposable app data clear, no Android hardware
        val second = store().use { it.publicIdentity() }
        assertNotEquals(first.installationId, second.installationId)
        assertNotEquals(first.verificationKeySha256, second.verificationKeySha256)
        assertNotEquals(first.publicKeyBase64, second.publicKeyBase64)
        assertTrue(Files.isRegularFile(state))
    }

    @Test
    fun tN6A03NoRawPrivateKeyBytesInPrivateStateOrPublicMcpStatus() {
        val public = store().use { it.publicIdentity() }
        val data = Files.readString(
            privateRoot.resolve("native-mcp-install-identity").resolve("installation.v1"))
        assertTrue(data.contains(public.verificationKeySha256))
        assertFalse(data.contains("BEGIN " + "PRIVATE KEY"))
        assertFalse(data.contains("PRIVATE KEY"))
        assertFalse(data.contains("pkcs8"))
        assertFalse(data.contains("private_key"))
        assertFalse(data.contains("serial_number"))
        assertEquals(1, backend.keys.size)
        assertTrue(data.length < 2048)
        assertFalse(public.encode().contains("private"))
    }

    @Test
    fun tN6A04FgsRestartKeepsInstallButExpiresChallengeAndEpoch() {
        val challenge: String
        val firstPublic: NativePublicInstallationIdentity
        val oldEpoch: String
        val signature: ByteArray
        store().use { first ->
            firstPublic = first.publicIdentity()
            oldEpoch = first.processEpoch
            challenge = first.beginSyntheticChallenge()
            signature = backend.sign(backend.lastAlias!!, challenge.toByteArray())!!
        }
        store().use { second ->
            assertEquals(firstPublic, second.publicIdentity())
            assertNotEquals(oldEpoch, second.processEpoch)
            assertFalse(second.verifySyntheticProof(challenge, signature))
            val fresh = second.beginSyntheticChallenge()
            val freshSig = backend.sign(backend.lastAlias!!, fresh.toByteArray())!!
            assertTrue(second.verifySyntheticProof(fresh, freshSig))
            assertFalse(second.verifySyntheticProof(fresh, freshSig))
        }
    }

    @Test
    fun tN6A05CorruptedPrivateStorageAndConcurrentFirstStartFailClosed() {
        val first = store()
        try {
            assertThrows(IllegalStateException::class.java) { store() }
        } finally { first.close() }
        val state = privateRoot.resolve("native-mcp-install-identity").resolve("installation.v1")
        Files.writeString(state, "forged-install-id|invalid public key")
        assertThrows(IllegalStateException::class.java) { store() }
        assertEquals(1, backend.keys.size)
    }

    @Test
    fun tN6A06ModelIdentityStringOrAdbSerialCannotForgeSignedChallenge() {
        store().use { owner ->
            val genuine = owner.publicIdentity()
            val challenge = owner.beginSyntheticChallenge()
            val forged = "adb-emulator-5554".toByteArray()
            assertFalse(owner.verifySyntheticProof(challenge, forged))
            val other = FakeKeystore()
            val otherAlias = "attacker-test-key"
            other.createKey(otherAlias)
            val forgedSig = other.sign(otherAlias, challenge.toByteArray())!!
            assertFalse(owner.verifySyntheticProof(challenge, forgedSig))
            assertEquals(genuine.installationId, owner.publicIdentity().installationId)
        }
    }

    @Test
    fun recordTamperUsingValidSyntaxCannotReplaceSignedInstallIdentity() {
        val public = store().use { it.publicIdentity() }
        val record = privateRoot.resolve("native-mcp-install-identity")
            .resolve("installation.v1")
        val original = Files.readString(record)
        Files.writeString(record, original.replace(
            public.installationId, "ffffffff-ffff-4fff-8fff-ffffffffffff",
        ))
        assertThrows(IllegalStateException::class.java) { store() }
        assertEquals(1, backend.keys.size)
    }

    @Test
    fun symlinkedPrivateRootAndStateAreRejectedWithoutReadOrKeyChange() {
        val owned = store().use { it.publicIdentity() }
        val directory = privateRoot.resolve("native-mcp-install-identity")
        val record = directory.resolve("installation.v1")
        val copied = privateRoot.resolve("outside-synthetic-installation")
        Files.copy(record, copied)
        Files.delete(record)
        Files.createSymbolicLink(record, copied)
        assertThrows(IllegalStateException::class.java) { store() }
        assertEquals(1, backend.keys.size)
        assertTrue(Files.readString(copied).contains(owned.verificationKeySha256))
    }

    @Test
    fun challengeClockRollbackAndReplayFailWithoutExportingPrivateKey() {
        store().use { owner ->
            val first = owner.beginSyntheticChallenge()
            val sig = backend.sign(backend.lastAlias!!, first.toByteArray())!!
            now.set(999)
            assertFalse(owner.verifySyntheticProof(first, sig))
            now.set(1000)
            assertFalse(owner.verifySyntheticProof(first, sig))
            val next = owner.beginSyntheticChallenge()
            val nextSignature = backend.sign(backend.lastAlias!!, next.toByteArray())!!
            now.set(32_000)
            assertFalse(owner.verifySyntheticProof(next, nextSignature))
            assertFalse(owner.verifySyntheticProof(next, nextSignature))
            assertEquals(1, backend.keys.size)
        }
    }

    @Test
    fun privateOwnerConcurrentStartupFailsWithoutIssuingSecondKey() {
        val primary = store()
        val executor = java.util.concurrent.Executors.newFixedThreadPool(6)
        val ready = java.util.concurrent.CountDownLatch(6)
        val start = java.util.concurrent.CountDownLatch(1)
        try {
            val futures = (0 until 6).map {
                executor.submit<Boolean> {
                    ready.countDown()
                    start.await(5, java.util.concurrent.TimeUnit.SECONDS)
                    try { store().use { true } } catch (_: IllegalStateException) { false }
                }
            }
            assertTrue(ready.await(5, java.util.concurrent.TimeUnit.SECONDS))
            start.countDown()
            assertTrue(futures.none { it.get(5, java.util.concurrent.TimeUnit.SECONDS) })
            assertEquals(1, backend.keys.size)
        } finally {
            start.countDown()
            executor.shutdownNow()
            primary.close()
        }
    }
}

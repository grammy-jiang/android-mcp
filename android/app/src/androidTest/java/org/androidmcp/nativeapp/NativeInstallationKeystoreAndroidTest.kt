package org.androidmcp.nativeapp

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.security.KeyFactory
import java.security.KeyStore
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import org.androidmcp.lifecycle.NativeInstallationIdentity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** E02.c prerequisite: genuine Android APK Keystore, not the JVM mock. */
@RunWith(AndroidJUnit4::class)
class NativeInstallationKeystoreAndroidTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun openOwner(): NativeInstallationIdentity =
        NativeInstallationIdentity(
            context.noBackupFilesDir.toPath(),
            AndroidInstallationKeystoreProvider(),
            SystemClock::elapsedRealtime,
        )

    @Test
    fun realInstalledAppKeystoreCreatesNonexportablePersistentPrivateKey() {
        val before = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        openOwner().use { owner ->
            val public = owner.publicIdentity()
            assertTrue(public.installationId.matches(Regex("[a-f0-9-]{36}")))
            assertTrue(public.verificationKeySha256.matches(Regex("[a-f0-9]{64}")))
            assertFalse(public.encode().contains("private_key"))
            val keystore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            val signing = keystore.getKey("android-mcp-native-install-signing-v1", null)
            assertNotNull(signing)
            assertTrue("Android private key material must never export", signing!!.encoded == null)
            assertTrue(keystore.containsAlias("android-mcp-native-install-signing-v1"))
        }
    }

    @Test
    fun genuineKeystoreSignatureVerifiesButForgedPeerCannotEnroll() {
        openOwner().use { owner ->
            val value = owner.publicIdentity()
            val challenge = owner.beginSyntheticChallenge()
            val data = challenge.toByteArray(Charsets.US_ASCII)
            val signed = AndroidInstallationKeystoreProvider()
                .sign("android-mcp-native-install-signing-v1", data)
            assertNotNull(signed)
            val public = KeyFactory.getInstance("EC").generatePublic(
                X509EncodedKeySpec(Base64.getDecoder().decode(value.publicKeyBase64))
            )
            assertTrue(Signature.getInstance("SHA256withECDSA").run {
                initVerify(public)
                update(data)
                verify(signed)
            })
            assertFalse(owner.verifySyntheticProof(challenge, byteArrayOf(1, 2, 3)))
            assertFalse("Rejected challenge must not be replayable", owner.verifySyntheticProof(challenge, signed!!))
        }
    }

    @Test
    fun privateInstallationRecordSurvivesClosingOneOwnerWithoutNewIdentity() {
        val initial = openOwner().use { it.publicIdentity() }
        val restarted = openOwner().use { it.publicIdentity() }
        assertEquals(initial, restarted)
        assertNotEquals("", restarted.verificationKeySha256)
    }

    @Test
    fun secondConcurrentActivityOwnerIsRejectedUntilLockReleased() {
        val first = openOwner()
        try {
            try {
                openOwner().use { throw AssertionError("Second owner unexpectedly acquired") }
                throw AssertionError("Second active owner must not coexist")
            } catch (_: IllegalStateException) {
                // Exact exclusive OS file lock rejects a second active owner.
            }
        } finally {
            first.close()
        }
        openOwner().use { assertTrue(it.publicIdentity().verificationKeySha256.isNotBlank()) }
    }
}

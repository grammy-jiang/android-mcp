package org.androidmcp.v3tlsfixture

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.math.BigInteger
import java.net.InetAddress
import java.nio.charset.StandardCharsets
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.SecureRandom
import java.security.Signature
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.Date
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket
import javax.net.ssl.TrustManagerFactory
import javax.security.auth.x500.X500Principal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * E02.a diagnostic POC, separate test-only APK (NOT a production listener).
 *
 * An AndroidKeyStore backed private key never leaves Android; Host has
 * separately generated, ephemeral, pinned client identity. The sole listener
 * binds 127.0.0.1 while AndroidJUnitRunner is alive and closes in finally.
 * ADB forward is only the transport, NOT permission/authentication.
 */
@RunWith(AndroidJUnit4::class)
class MutualTlsAndroidTest {
    private val tag = "NativeV3TlsPoc"

    private fun readBoundedRequest(socket: SSLSocket): String {
        val bytes = ByteArrayOutputStream()
        repeat(100) {
            val ch = socket.inputStream.read()
            if (ch < 0) throw IOException("TLS peer closed before message")
            if (ch == 10) return bytes.toString(StandardCharsets.UTF_8.name())
            bytes.write(ch)
        }
        throw IOException("Bounded TLS request exceeded 100 bytes")
    }

    @Test
    fun realKeystoreMutualTlsRequiresPinnedClient() {
        val args = InstrumentationRegistry.getArguments()
        val nonce = requireNotNull(args.getString("run_nonce"))
        require(Regex("[0-9a-f]{24}").matches(nonce)) { "Invalid test nonce" }
        val clientEncoded = requireNotNull(args.getString("client_cert_base64"))
        require(clientEncoded.length in 128..6000) { "Pinned certificate oversized/absent" }
        val clientCert = CertificateFactory.getInstance("X.509").generateCertificate(
            ByteArrayInputStream(Base64.decode(clientEncoded, Base64.NO_WRAP))
        ) as X509Certificate
        clientCert.checkValidity()

        val alias = "native-v3-tls-poc-$nonce"
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        assertFalse(store.containsAlias(alias))
        try {
            val generator = KeyPairGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore"
            )
            generator.initialize(
                KeyGenParameterSpec.Builder(
                    alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
                )
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                    .setDigests(
                        KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512,
                        KeyProperties.DIGEST_NONE
                    )
                    .setCertificateSubject(X500Principal("CN=Android MCP V3 TLS Test"))
                    .setCertificateSerialNumber(BigInteger.ONE)
                    .setCertificateNotBefore(Date(System.currentTimeMillis() - 3600_000))
                    .setCertificateNotAfter(Date(System.currentTimeMillis() + 3600_000))
                    .setUserAuthenticationRequired(false)
                    .build()
            )
            val pair = generator.generateKeyPair()
            assertTrue(pair.private.encoded == null)

            val freshStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            val certificate = freshStore.getCertificate(alias) as X509Certificate
            val bytes = byteArrayOf(0x4d, 0x43, 0x50, 0x33)
            val signer = Signature.getInstance("SHA256withECDSA")
            signer.initSign(pair.private)
            signer.update(bytes)
            val signature = signer.sign()
            val verifier = Signature.getInstance("SHA256withECDSA")
            verifier.initVerify(certificate.publicKey)
            verifier.update(bytes)
            assertTrue("Keystore signing is not usable", verifier.verify(signature))

            val managers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
                .apply { init(freshStore, null) }
            val hostTrust = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null, null)
                setCertificateEntry("pinned-single-host-cert", clientCert)
            }
            val trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
                .apply { init(hostTrust) }
            val ctx = SSLContext.getInstance("TLS").apply {
                init(managers.keyManagers, trust.trustManagers, SecureRandom())
            }
            val listener = ctx.serverSocketFactory.createServerSocket(
                0, 3, InetAddress.getByName("127.0.0.1")
            ) as SSLServerSocket
            listener.use { server ->
                server.needClientAuth = true
                server.enabledProtocols = arrayOf("TLSv1.2")
                server.enabledCipherSuites = arrayOf("TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256")
                assertTrue(server.enabledProtocols.isNotEmpty())
                server.soTimeout = 25_000
                Log.i(
                    tag,
                    "READY nonce=$nonce port=${server.localPort} cert_base64=" +
                        Base64.encodeToString(certificate.encoded, Base64.NO_WRAP)
                )
                var denied = 0
                var accepted = 0
                repeat(3) { index ->
                    (server.accept() as SSLSocket).use { client ->
                        client.soTimeout = 15_000
                        client.enabledProtocols = server.enabledProtocols
                        try {
                            client.startHandshake()
                            val peer = client.session.peerCertificates.first() as X509Certificate
                            if (!peer.encoded.contentEquals(clientCert.encoded)) {
                                throw IOException("Unpinned peer")
                            }
                            val request = readBoundedRequest(client)
                            if (request != "POC=$nonce") throw IOException("Wrong nonce")
                            client.outputStream.write("TLS_OK=$nonce\n".toByteArray(Charsets.UTF_8))
                            client.outputStream.flush()
                            accepted++
                        } catch (error: SSLException) {
                            Log.i(tag, "DENIED nonce=$nonce index=$index reason=" + error.javaClass.simpleName)
                            denied++
                        } catch (error: IOException) {
                            Log.i(tag, "DENIED nonce=$nonce index=$index reason=" + error.javaClass.simpleName)
                            denied++
                        }
                    }
                }
                Log.i(tag, "COMPLETE nonce=$nonce allowed=$accepted denied=$denied")
                assertEquals("Correct single Host identity must be accepted once", 1, accepted)
                assertEquals("No-cert and wrong Host certificate must fail", 2, denied)
            }
        } finally {
            store.deleteEntry(alias)
            assertFalse(store.containsAlias(alias))
        }
    }
}

package org.androidmcp.v3tlsfixture

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.ByteArrayInputStream
import java.io.IOException
import java.math.BigInteger
import java.net.InetAddress
import java.net.Socket
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Principal
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Signature
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.Date
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLEngine
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509ExtendedKeyManager
import javax.security.auth.x500.X500Principal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * E02.a reverse-initiated AndroidKeyStore mTLS POC, test-only APK.
 *
 * Android explicitly dials only 127.0.0.1 through a separately owned ADB
 * reverse mapping. Both peer certs are pinned. No Native production listener,
 * no exported Activity/Service and no Android API privilege bypass.
 */
@RunWith(AndroidJUnit4::class)
class MutualTlsClientAndroidTest {
    private val tag = "NativeV3TlsClient"

    private fun generateTemporaryKey(alias: String): X509Certificate {
        val generator = KeyPairGenerator.getInstance("EC", "AndroidKeyStore")
        generator.initialize(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
            )
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(
                    KeyProperties.DIGEST_SHA256,
                    KeyProperties.DIGEST_SHA512,
                    KeyProperties.DIGEST_NONE,
                )
                .setCertificateSubject(X500Principal("CN=Android MCP V3 Test Client"))
                .setCertificateSerialNumber(BigInteger.ONE)
                .setCertificateNotBefore(Date(System.currentTimeMillis() - 3600_000))
                .setCertificateNotAfter(Date(System.currentTimeMillis() + 3600_000))
                .setUserAuthenticationRequired(false)
                .build()
        )
        val pair = generator.generateKeyPair()
        assertTrue("Android private key must not be exportable", pair.private.encoded == null)
        val certificate = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            .getCertificate(alias) as X509Certificate
        val signature = Signature.getInstance("SHA256withECDSA")
        signature.initSign(pair.private)
        signature.update(byteArrayOf(77, 67, 80, 51))
        val proof = signature.sign()
        signature.initVerify(certificate.publicKey)
        signature.update(byteArrayOf(77, 67, 80, 51))
        assertTrue("AndroidKeyStore private signer inaccessible", signature.verify(proof))
        return certificate
    }

    private fun pinnedKeyManager(
        store: KeyStore, alias: String, chain: X509Certificate
    ): X509ExtendedKeyManager = object : X509ExtendedKeyManager() {
        override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?): Array<String>? =
            if (keyType == "EC" || keyType == "EC_EC") arrayOf(alias) else null
        override fun chooseClientAlias(
            keyTypes: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?
        ): String? = if (keyTypes?.any { it == "EC" || it == "EC_EC" } == true) alias else null
        override fun chooseEngineClientAlias(
            keyTypes: Array<out String>?, issuers: Array<out Principal>?, engine: SSLEngine?
        ): String? = chooseClientAlias(keyTypes, issuers, null)
        override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?): Array<String>? = null
        override fun chooseServerAlias(
            keyType: String?, issuers: Array<out Principal>?, socket: Socket?
        ): String? = null
        override fun chooseEngineServerAlias(
            keyType: String?, issuers: Array<out Principal>?, engine: SSLEngine?
        ): String? = null
        override fun getCertificateChain(aliasName: String?): Array<X509Certificate>? =
            if (aliasName == alias) arrayOf(chain) else null
        override fun getPrivateKey(aliasName: String?): PrivateKey? =
            if (aliasName == alias) store.getKey(alias, null) as? PrivateKey else null
    }

    private fun client(
        hostCert: X509Certificate, alias: String?, store: KeyStore,
        cert: X509Certificate?
    ): SSLContext {
        val trustStore = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null)
            setCertificateEntry("pinned-host", hostCert)
        }
        val trustFactory = TrustManagerFactory.getInstance(
            TrustManagerFactory.getDefaultAlgorithm()
        ).apply { init(trustStore) }
        val managers = if (alias == null || cert == null) null else arrayOf(
            pinnedKeyManager(store, alias, cert)
        )
        return SSLContext.getInstance("TLS").apply {
            init(managers, trustFactory.trustManagers, SecureRandom())
        }
    }

    private fun attempt(
        context: SSLContext, port: Int, nonce: String, good: Boolean
    ): Boolean {
        try {
            (context.socketFactory.createSocket(
                InetAddress.getByName("127.0.0.1"), port
            ) as SSLSocket).use { socket ->
                socket.soTimeout = 12_000
                socket.enabledProtocols = arrayOf("TLSv1.2")
                val params = socket.sslParameters
                params.endpointIdentificationAlgorithm = "HTTPS"
                socket.sslParameters = params
                socket.startHandshake()
                socket.outputStream.write("POC=$nonce\n".toByteArray(Charsets.US_ASCII))
                socket.outputStream.flush()
                val answer = ByteArray(100)
                val n = socket.inputStream.read(answer)
                if (n > 0 && String(answer, 0, n, Charsets.US_ASCII) == "TLS_OK=$nonce\n") {
                    if (!good) throw IOException("Host incorrectly accepted wrong client")
                    return true
                }
                if (good) throw IOException("Pinned correct client got wrong answer")
                return false
            }
        } catch (error: SSLException) {
            Log.i(tag, "DENIED nonce=$nonce error=" + error.javaClass.simpleName)
            if (good) throw error
            return false
        } catch (error: IOException) {
            Log.i(tag, "DENIED nonce=$nonce error=" + error.javaClass.simpleName)
            if (good) throw error
            return false
        }
    }

    @Test
    fun androidKeyStoreClientNeedsPinnedHostAndClientTrust() {
        val args = InstrumentationRegistry.getArguments()
        val nonce = requireNotNull(args.getString("run_nonce"))
        require(Regex("[a-f0-9]{24}").matches(nonce))
        val port = requireNotNull(args.getString("reverse_port")).toInt()
        require(port in 1024..65535)
        val hostBase64 = requireNotNull(args.getString("host_cert_base64"))
        require(hostBase64.length in 128..6000)
        val hostCert = CertificateFactory.getInstance("X.509").generateCertificate(
            ByteArrayInputStream(Base64.decode(hostBase64, Base64.NO_WRAP))
        ) as X509Certificate
        hostCert.checkValidity()

        val trusted = "v3-tls-client-good-$nonce"
        val wrong = "v3-tls-client-wrong-$nonce"
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        require(!store.containsAlias(trusted) && !store.containsAlias(wrong))
        try {
            val goodCert = generateTemporaryKey(trusted)
            val badCert = generateTemporaryKey(wrong)
            Log.i(
                tag,
                "READY nonce=$nonce port=$port cert_base64=" +
                    Base64.encodeToString(goodCert.encoded, Base64.NO_WRAP)
            )
            Thread.sleep(3_000) // bounded transport bootstrap in owned emulator
            val deniedAnonymous = !attempt(client(hostCert, null, store, null), port, nonce, false)
            val deniedWrong = !attempt(client(hostCert, wrong, store, badCert), port, nonce, false)
            val acceptedTrusted = attempt(client(hostCert, trusted, store, goodCert), port, nonce, true)
            val allowed = if (acceptedTrusted) 1 else 0
            val denied = listOf(deniedAnonymous, deniedWrong).count { it }
            Log.i(tag, "COMPLETE nonce=$nonce allowed=$allowed denied=$denied")
            assertEquals(1, allowed)
            assertEquals(2, denied)
        } finally {
            store.deleteEntry(trusted)
            store.deleteEntry(wrong)
            assertTrue(!store.containsAlias(trusted) && !store.containsAlias(wrong))
        }
    }
}

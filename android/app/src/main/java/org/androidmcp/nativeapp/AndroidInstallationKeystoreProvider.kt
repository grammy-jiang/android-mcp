package org.androidmcp.nativeapp

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import org.androidmcp.lifecycle.NativeInstallationSigningProvider
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * AndroidKeyStore-backed internal key interface for N6.a.
 *
 * A signing operation stays within the Android Keystore provider; private
 * key material is never read as bytes or written into the app sandbox.
 * No public MCP handler or Activity currently invokes this provider.
 */
internal class AndroidInstallationKeystoreProvider : NativeInstallationSigningProvider {
    private fun load(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply {
        load(null)
    }

    override fun createKey(alias: String): ByteArray {
        require(alias == OWNED_ALIAS)
        val generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore",
        )
        generator.initialize(
            KeyGenParameterSpec.Builder(
                alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
            ).setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(false)
                .build(),
        )
        return generator.generateKeyPair().public.encoded
    }

    override fun publicKey(alias: String): ByteArray? {
        require(alias == OWNED_ALIAS)
        return load().getCertificate(alias)?.publicKey?.encoded
    }

    override fun sign(alias: String, challenge: ByteArray): ByteArray? {
        require(alias == OWNED_ALIAS)
        if (challenge.size !in 1..256) return null
        val signingKey = load().getKey(alias, null) as? PrivateKey ?: return null
        return Signature.getInstance("SHA256withECDSA").run {
            initSign(signingKey)
            update(challenge)
            sign()
        }
    }

    override fun deleteKey(alias: String) {
        require(alias == OWNED_ALIAS)
        load().deleteEntry(alias)
    }

    companion object {
        private const val OWNED_ALIAS = "android-mcp-native-install-signing-v1"
    }
}

package org.androidmcp.protocol

import java.security.KeyFactory
import java.security.MessageDigest
import java.security.PublicKey
import java.security.SecureRandom
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

/** N6.b independent, synthetic-only signed Host challenge policy. */
enum class PairingProofState {
    FAKE_RECOGNIZED, DENIED, STALE, REPLAY, EXPIRED, OVER_CAPACITY, UNSUPPORTED,
    UNAVAILABLE,
}

data class SyntheticPairChallenge(
    val packet: String,
    val nonce: String,
    val expiresAtElapsedMs: Long,
) {
    override fun toString() = "SyntheticPairChallenge([REDACTED])"
}

data class SyntheticPairProof(
    val packet: String,
    val signatureDer: ByteArray,
    val declaredOrigin: String,
    val declaredHostId: String,
) {
    override fun toString() = "SyntheticPairProof([REDACTED])"
}

/**
 * Fake signature verification cannot activate a Native pairing route.
 * The real shared protocol has not been jointly agreed and registered;
 * only typed test-model FAKE_RECOGNIZED status is returned.
 */
class NativePairingChallenge(
    private val instanceId: String,
    private val bootEpoch: String,
    private val hostIdentity: String,
    private val hostPublicSpki: ByteArray,
    private val allowedOrigin: String,
    private val elapsedClockMs: () -> Long,
) {
    private data class Pending(val packet: String, val issued: Long, val expiry: Long)
    private val pending = LinkedHashMap<String, Pending>()
    private var stopped = false
    private var latestClock = -1L
    private val publicKey: PublicKey? = try {
        val key = KeyFactory.getInstance("EC").generatePublic(
            X509EncodedKeySpec(hostPublicSpki),
        )
        if (key is ECPublicKey && key.params.curve.field.fieldSize == 256 &&
            hostPublicSpki.size in 60..300
        ) key else null
    } catch (_: Exception) { null }

    @Synchronized
    fun begin(host: String, origin: String, planDigest: String): SyntheticPairChallenge? {
        if (stopped || !validContext() || host != hostIdentity ||
            origin != allowedOrigin || !DIGEST.matches(planDigest)
        ) return null
        val now = clock() ?: return null
        pending.entries.removeIf { it.value.expiry < now }
        if (pending.size >= MAX_PENDING || now > Long.MAX_VALUE - TTL_MS) return null
        val random = ByteArray(24)
        RANDOM.nextBytes(random)
        val nonce = Base64.getUrlEncoder().withoutPadding().encodeToString(random)
        val packet = listOf(
            "N6B2", instanceId, bootEpoch, hostIdentity,
            origin, planDigest, nonce, now.toString(),
        ).joinToString("|")
        if (packet.toByteArray(Charsets.UTF_8).size > MAX_PACKET) return null
        pending[nonce] = Pending(packet, now, now + TTL_MS)
        return SyntheticPairChallenge(packet, nonce, now + TTL_MS)
    }

    @Synchronized
    fun accept(proof: SyntheticPairProof): PairingProofState {
        if (stopped || !validContext()) return PairingProofState.UNAVAILABLE
        if (proof.packet.toByteArray(Charsets.UTF_8).size !in 64..MAX_PACKET ||
            proof.signatureDer.size !in 8..256 ||
            proof.declaredOrigin != allowedOrigin ||
            proof.declaredHostId != hostIdentity
        ) return PairingProofState.DENIED
        val parts = proof.packet.split('|')
        if (parts.size != 8 || parts[0] != "N6B2" ||
            parts[1] != instanceId || parts[2] != bootEpoch ||
            parts[3] != hostIdentity || parts[4] != allowedOrigin ||
            !DIGEST.matches(parts[5]) || !NONCE.matches(parts[6])
        ) return PairingProofState.DENIED
        val nonce = parts[6]
        val now = clock() ?: return PairingProofState.UNAVAILABLE
        val pendingProof = pending.remove(nonce) ?: return PairingProofState.REPLAY
        if (now < pendingProof.issued || now > pendingProof.expiry) {
            return PairingProofState.EXPIRED
        }
        if (pendingProof.packet != proof.packet) return PairingProofState.DENIED
        val verified = try {
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(publicKey)
                update(proof.packet.toByteArray(Charsets.UTF_8))
                verify(proof.signatureDer)
            }
        } catch (_: Exception) { false }
        return if (verified) PairingProofState.FAKE_RECOGNIZED else PairingProofState.DENIED
    }

    @Synchronized
    fun activeCount(): Int = pending.size

    @Synchronized
    fun stop() {
        stopped = true
        pending.clear()
    }

    fun productionPairingEnabled(): Boolean = false

    private fun validContext(): Boolean =
        publicKey != null && IDENT.matches(instanceId) &&
            IDENT.matches(bootEpoch) && IDENT.matches(hostIdentity) &&
            allowedOrigin == "http://127.0.0.1:38765"

    private fun clock(): Long? {
        val value = elapsedClockMs()
        if (value < 0 || (latestClock >= 0 && value < latestClock)) {
            stopped = true
            pending.clear()
            return null
        }
        latestClock = value
        return value
    }

    companion object {
        private const val TTL_MS = 15_000L
        private const val MAX_PENDING = 100
        private const val MAX_PACKET = 1024
        private val IDENT = Regex("[A-Za-z0-9_-]{8,128}")
        private val DIGEST = Regex("[a-f0-9]{64}")
        private val NONCE = Regex("[A-Za-z0-9_-]{32}")
        private val RANDOM = SecureRandom()
    }
}

package org.androidmcp.protocol

import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativePairingChallengeTest {
    private val now = AtomicLong(10_000)
    private val origin = "http://127.0.0.1:38765"
    private val host = "trusted-host-identity"
    private val instance = "native-install-identity"
    private val boot = "native-boot-epoch"
    private val plan = "a".repeat(64)
    private val signer: KeyPair = KeyPairGenerator.getInstance("EC").apply {
        initialize(ECGenParameterSpec("secp256r1"))
    }.generateKeyPair()
    private fun policy() = NativePairingChallenge(
        instance, boot, host, signer.public.encoded, origin, now::get,
    )
    private fun signed(challenge: SyntheticPairChallenge, key: KeyPair = signer) =
        SyntheticPairProof(challenge.packet, Signature.getInstance("SHA256withECDSA").run {
            initSign(key.private); update(challenge.packet.toByteArray()); sign()
        }, origin, host)

    @Test
    fun tN6B01SignedHostNonceBindsVersionNativeInstanceBootAndDigest() {
        val fixture = policy()
        val challenge = fixture.begin(host, origin, plan)!!
        assertTrue(challenge.packet.startsWith("N6B2|$instance|$boot|$host|$origin|$plan|"))
        assertEquals(PairingProofState.FAKE_RECOGNIZED, fixture.accept(signed(challenge)))
        assertFalse(fixture.productionPairingEnabled())
        assertEquals(0, fixture.activeCount())
    }

    @Test
    fun tN6B02WrongSignerOriginDigestReplayCrossDeviceAndExpiryDenied() {
        val fixture = policy()
        val challenge = fixture.begin(host, origin, plan)!!
        val wrongKey = KeyPairGenerator.getInstance("EC").apply {
            initialize(ECGenParameterSpec("secp256r1"))
        }.generateKeyPair()
        assertEquals(PairingProofState.DENIED,
            fixture.accept(signed(challenge, wrongKey)))
        assertEquals(PairingProofState.REPLAY, fixture.accept(signed(challenge)))
        val next = fixture.begin(host, origin, plan)!!
        assertEquals(PairingProofState.DENIED, fixture.accept(
            signed(next).copy(declaredOrigin = "https://evil.example"),
        ))
        val tamper = fixture.begin(host, origin, plan)!!
        assertEquals(PairingProofState.DENIED,
            fixture.accept(signed(tamper).copy(packet =
                tamper.packet.replace(plan, "b".repeat(64)))))
        val foreign = NativePairingChallenge(
            "other-native-install-id", boot, host, signer.public.encoded, origin, now::get,
        )
        assertEquals(PairingProofState.DENIED, foreign.accept(signed(next)))
        val expires = fixture.begin(host, origin, plan)!!
        now.set(30_000)
        assertEquals(PairingProofState.EXPIRED, fixture.accept(signed(expires)))
    }

    @Test
    fun tN6B03LoopbackStatusNeverBecomesMutationApproval() {
        val guard = NativeLocalCallerGuard()
        val fake = SyntheticCallerApproval(guard.epoch, "fake-proof", true)
        assertFalse(guard.authorizeSensitive(
            LocalHttpRequest(), "native_capture_screen", fake,
        ).allowed)
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        assertFalse(policy().productionPairingEnabled())
        assertNull(policy().begin(host, "https://other.example", plan))
    }

    @Test
    fun tN6B04ServiceRestartAndUsbReconnectCannotReuseTransientChallenge() {
        val first = policy()
        val earlier = first.begin(host, origin, plan)!!
        first.stop()
        assertEquals(PairingProofState.UNAVAILABLE, first.accept(signed(earlier)))
        val restarted = policy()
        assertEquals(PairingProofState.REPLAY, restarted.accept(signed(earlier)))
        assertEquals(PairingProofState.FAKE_RECOGNIZED,
            restarted.accept(signed(restarted.begin(host, origin, plan)!!)))
    }

    @Test
    fun tN6B05HundredConcurrentAttemptsBoundedPacketAndClockRollback() {
        val fixture = policy()
        val worker = Executors.newFixedThreadPool(12)
        val go = CountDownLatch(1)
        try {
            val results = (0 until 100).map {
                worker.submit(Callable {
                    go.await(5, TimeUnit.SECONDS)
                    fixture.begin(host, origin, plan)
                })
            }
            go.countDown()
            val issued = results.map { it.get(10, TimeUnit.SECONDS)!! }
            assertEquals(100, issued.map { it.nonce }.toSet().size)
            assertEquals(100, fixture.activeCount())
            assertNull(fixture.begin(host, origin, plan))
            assertNull(fixture.begin(host, origin, "z".repeat(100_000)))
            now.set(9000)
            assertEquals(PairingProofState.UNAVAILABLE, fixture.accept(signed(issued.first())))
            assertEquals(0, fixture.activeCount())
        } finally { go.countDown(); worker.shutdownNow() }
    }

    @Test
    fun tN6B06AbsentJointContractNeverRegistersLivePairingRoute() {
        val fixture = policy()
        val challenge = fixture.begin(host, origin, plan)!!
        assertEquals(PairingProofState.FAKE_RECOGNIZED, fixture.accept(signed(challenge)))
        assertFalse(fixture.productionPairingEnabled())
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
    }
}

package org.androidmcp.protocol

import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Test

/** E02.b the actual Kotlin/JVM Native protocol reader consumes the same v2
 * fixtures as the Python Host reference; no simulated pairing grant.
 */
class NativeSecurityWireV2Test {
    private val fixtures = File(
        System.getProperty("androidMcp.contractsRoot"), "v2/fixtures",
    )
    private val kinds = listOf(
        "pair_challenge", "pair_proof", "session_authorization",
        "operation_grant", "lease_acquire", "lease_receipt",
    )
    private val boot = "bf038b5a-d3ba-47e3-940a-dfc5ca86182b"
    private val now = 1791940000500L

    private fun bytes(kind: String): ByteArray =
        File(fixtures, "$kind.v2.json").readBytes()

    private fun inspect(source: ByteArray): NativeV2Inspection? =
        NativeSecurityWireV2.inspect(
            source,
            nowMs = now,
            hostSpkiSha256 = "2".repeat(64),
            nativeSpkiSha256 = "3".repeat(64),
            bootEpoch = boot,
        )

    @Test
    fun allSixFixtureKindsAreDecodedAndRoundTripped() {
        kinds.forEach { kind ->
            val original = bytes(kind)
            val output = assertNotNull(inspect(original), kind)
            assertEquals(kind, output.kind)
            assertEquals("47707d52-ecf5-454d-9d28-a364bbbf9eba", output.sessionId)
            assertEquals(
                Json.parseToJsonElement(original.decodeToString()),
                Json.parseToJsonElement(output.encode()),
            )
            assertFalse(output.authorized)
            assertFalse(output.consentVerified)
            assertFalse(output.leaseHeld)
        }
    }

    @Test
    fun topLevelAttackerClaimsAndVersionDowngradeFailClosed() {
        val original = bytes("pair_challenge").decodeToString()
        listOf(
            original.replace("\"schema_version\": 2", "\"schema_version\": 1"),
            original.replace("\"kind\": \"pair_challenge\"", "\"kind\": \"shell\""),
            original.replace(
                "\"host_spki_sha256\": \"${"2".repeat(64)}\"",
                "\"host_spki_sha256\": \"${"f".repeat(64)}\"",
            ),
            original.replace(
                "\"native_boot_epoch\": \"$boot\"",
                "\"native_boot_epoch\": \"00000000-0000-4000-8000-000000000000\"",
            ),
            original.replace("\"issued_at_unix_ms\": 1791940000000", "\"issued_at_unix_ms\": 1791940020000"),
            original.replace(
                "\"schema_version\": 2",
                "\"schema_version\": 2, \"approved\": true",
            ),
        ).forEach { mutant ->
            assertNull(inspect(mutant.toByteArray(Charsets.UTF_8)))
        }
    }

    @Test
    fun noDuplicateKeysOrOversizedBytesMayReachARealTool() {
        val original = bytes("pair_challenge").decodeToString()
        val malicious = original.replace(
            "\"nonce_b64u\":",
            "\"nonce_b64u\": \"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\", \"nonce_b64u\":",
        )
        assertNull(inspect(malicious.toByteArray()))
        assertNull(inspect(ByteArray(8300) { 'x'.code.toByte() }))
        assertNull(inspect(ByteArray(0)))
        assertNull(inspect(byteArrayOf(-1, -1)))
    }

    @Test
    fun noUnsupportedScopesFencesOrModelApprovedPayloads() {
        val base = bytes("lease_acquire").decodeToString()
        val payloads = listOf(
            base.replace("\"fence\": 13", "\"fence\": 0"),
            base.replace("\"ttl_ms\": 10000", "\"ttl_ms\": 9999999"),
            base.replace("\"scope\": \"approved_control\"", "\"scope\": \"root\""),
            base.replace("\"ttl_ms\": 10000", "\"ttl_ms\": 10000, \"approved\": true"),
        )
        payloads.forEach { assertNull(inspect(it.toByteArray())) }
        assertNotNull(inspect(bytes("lease_acquire")))
    }

    @Test
    fun escapedDuplicateJsonNamesAndNestedConflictingFramesAreDenied() {
        val sample = bytes("pair_challenge").decodeToString()
        val equivalentName = "\\u006eonce_b64u"
        val shadowKey = sample.replace(
            "\"nonce_b64u\":",
            "\"nonce_b64u\": \"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\", " +
                "\"$equivalentName\":",
        )
        assertNull(inspect(shadowKey.toByteArray(Charsets.UTF_8)))
        assertNull(inspect("[".toByteArray(Charsets.UTF_8)))
        assertNull(inspect("{\"schema_version\":2,\"schema_version\":2}".toByteArray()))
    }

    @Test
    fun actualLeaseReceiptMustNeverAdvertiseAutomaticRetry() {
        val sample = bytes("lease_receipt").decodeToString()
        assertNotNull(inspect(sample.toByteArray(Charsets.UTF_8)))
        val tampered = sample.replace(
            "\"retry_automatically\": false", "\"retry_automatically\": true",
        )
        assertNull(inspect(tampered.toByteArray(Charsets.UTF_8)))
    }

    @Test
    fun staleFramesAndClockMismatchesAreNeverAuthorized() {
        val sample = bytes("operation_grant")
        assertNotNull(inspect(sample))
        assertNull(NativeSecurityWireV2.inspect(
            sample, now + 20000, "2".repeat(64), "3".repeat(64), boot,
        ))
        assertNull(NativeSecurityWireV2.inspect(
            sample, now, "a".repeat(64), "3".repeat(64), boot,
        ))
        assertNull(NativeSecurityWireV2.inspect(
            sample, now, "2".repeat(64), "a".repeat(64), boot,
        ))
        assertNull(NativeSecurityWireV2.inspect(
            sample, now, "2".repeat(64), "3".repeat(64), "wrong-boot",
        ))
    }
}

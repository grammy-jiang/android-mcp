package org.androidmcp.protocol

import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

/**
 * E02.b C0 candidate: structural+context verification for a versioned v2
 * security wire frame. Parsing is NOT TLS peer proof, signature verification,
 * user consent, lease admission, scoped permission, or capability enablement.
 *
 * A caller cannot grant itself authority by declaring an approved payload.
 * Production E02.c–f MUST verify signer, live OS callback and durable
 * resource/replay/boot state independently before activating any Native Tool.
 */
class NativeV2Inspection internal constructor(
    val kind: String,
    val sessionId: String,
    private val raw: String,
) {
    val authorized: Boolean get() = false
    val consentVerified: Boolean get() = false
    val leaseHeld: Boolean get() = false
    fun encode(): String = raw
    override fun toString(): String = "NativeV2Inspection(kind=$kind, [REDACTED])"
}

object NativeSecurityWireV2 {
    const val MAX_BYTES: Int = 8192

    private val uuid = Regex("[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
    private val sha256 = Regex("[a-f0-9]{64}")
    private val nonce = Regex("[A-Za-z0-9_-]{40,64}")
    private val signature = Regex("[A-Za-z0-9_-]{64,512}")
    private val packageId = Regex("(?:[A-Za-z_][A-Za-z_0-9]*\\.)+[A-Za-z_][A-Za-z_0-9]*")

    private val rootKeys = setOf(
        "schema_version", "kind", "message_id", "session_id",
        "native_installation_id", "native_boot_epoch",
        "host_spki_sha256", "native_spki_sha256",
        "issued_at_unix_ms", "expires_at_unix_ms", "payload",
    )

    private val kinds = mapOf(
        "pair_challenge" to setOf("nonce_b64u"),
        "pair_proof" to setOf("nonce_b64u", "signature_der_b64u"),
        "session_authorization" to setOf(
            "scope", "tls_peer_spki_sha256", "state", "signature_der_b64u",
        ),
        "operation_grant" to setOf(
            "scope", "tool", "target_package", "operation_digest_sha256",
            "consent_event_id", "signature_der_b64u",
        ),
        "lease_acquire" to setOf(
            "scope", "tool", "target_package", "operation_digest_sha256",
            "fence", "ttl_ms", "grant_message_id",
        ),
        "lease_receipt" to setOf(
            "state", "fence", "dispatched", "retry_automatically",
            "operation_digest_sha256", "originating_request_id",
        ),
    )
    private val maxTtlByKind = mapOf(
        "pair_challenge" to 15_000L,
        "pair_proof" to 15_000L,
        "session_authorization" to 60_000L,
        "operation_grant" to 15_000L,
        "lease_acquire" to 15_000L,
        "lease_receipt" to 30_000L,
    )
    private val scopes = setOf("status", "read", "user_consented", "approved_control")
    private val operations = setOf(
        "native_capture_screen", "native_record_screen", "native_file_exchange",
        "native_ui_action", "native_app_launch", "native_install_request",
    )
    private val leaseStates = setOf(
        "held", "busy", "denied", "expired", "stopped",
        "releasing", "released", "uncertain", "replay",
    )

    fun inspect(
        frame: ByteArray,
        nowMs: Long,
        hostSpkiSha256: String,
        nativeSpkiSha256: String,
        bootEpoch: String,
    ): NativeV2Inspection? {
        if (frame.size !in 1..MAX_BYTES || nowMs < 0) return null
        val text = try {
            Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(frame)).toString()
        } catch (_: CharacterCodingException) {
            return null
        }
        if (!hasUniqueObjectKeys(text)) return null
        val obj = try {
            Json.parseToJsonElement(text) as? JsonObject ?: return null
        } catch (_: IllegalArgumentException) {
            return null
        }
        if (obj.keys != rootKeys || obj.long("schema_version") != 2L) return null
        val kind = obj.string("kind") ?: return null
        val fields = kinds[kind] ?: return null
        val session = obj.string("session_id") ?: return null
        for (key in listOf("message_id", "session_id", "native_installation_id", "native_boot_epoch")) {
            if (obj.string(key)?.matches(uuid) != true) return null
        }
        for (key in listOf("host_spki_sha256", "native_spki_sha256")) {
            if (obj.string(key)?.matches(sha256) != true) return null
        }
        if (
            obj.string("host_spki_sha256") != hostSpkiSha256 ||
            obj.string("native_spki_sha256") != nativeSpkiSha256 ||
            obj.string("native_boot_epoch") != bootEpoch
        ) return null

        val issued = obj.long("issued_at_unix_ms") ?: return null
        val expires = obj.long("expires_at_unix_ms") ?: return null
        val upper = maxTtlByKind[kind] ?: return null
        if (
            issued !in 946_684_800_000L..4_102_444_800_000L ||
            expires !in 946_684_800_000L..4_102_444_800_000L ||
            nowMs < issued || nowMs > expires || expires <= issued ||
            expires - issued > upper
        ) return null

        val payload = obj["payload"] as? JsonObject ?: return null
        if (payload.keys != fields || !validPayload(kind, payload, hostSpkiSha256)) return null
        // Validated *structure* remains untrusted even if it carries a
        // syntactically correct signature or consent reference.
        return NativeV2Inspection(kind, session, obj.toString())
    }

    private fun validPayload(
        kind: String,
        body: JsonObject,
        hostSpkiSha256: String,
    ): Boolean {
        fun String.matchesField(regex: Regex): Boolean = body.string(this)?.matches(regex) == true
        fun sha(field: String) = field.matchesField(sha256)
        fun validTool() = body.string("tool") in operations
        fun validTarget() = body.string("target_package")?.let {
            it.length in 3..160 && it.matches(packageId)
        } == true
        fun validFence() = body.long("fence")?.let { it in 1L..Long.MAX_VALUE } == true
        return when (kind) {
            "pair_challenge" -> "nonce_b64u".matchesField(nonce)
            "pair_proof" ->
                "nonce_b64u".matchesField(nonce) &&
                    "signature_der_b64u".matchesField(signature)
            "session_authorization" ->
                body.string("scope") in scopes &&
                    sha("tls_peer_spki_sha256") &&
                    body.string("tls_peer_spki_sha256") == hostSpkiSha256 &&
                    body.string("state") == "authenticated" &&
                    "signature_der_b64u".matchesField(signature)
            "operation_grant" ->
                body.string("scope") in setOf("user_consented", "approved_control") &&
                    validTool() && validTarget() && sha("operation_digest_sha256") &&
                    "consent_event_id".matchesField(uuid) &&
                    "signature_der_b64u".matchesField(signature)
            "lease_acquire" ->
                body.string("scope") == "approved_control" && validTool() &&
                    validTarget() && sha("operation_digest_sha256") && validFence() &&
                    body.long("ttl_ms")?.let { it in 100L..10_000L } == true &&
                    "grant_message_id".matchesField(uuid)
            "lease_receipt" ->
                body.string("state") in leaseStates && validFence() &&
                    body.bool("dispatched") != null &&
                    body.bool("retry_automatically") == false &&
                    sha("operation_digest_sha256") &&
                    "originating_request_id".matchesField(uuid)
            else -> false
        }
    }

    private fun JsonObject.string(field: String): String? =
        (get(field) as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun JsonObject.long(field: String): Long? =
        (get(field) as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull

    private fun JsonObject.bool(field: String): Boolean? =
        (get(field) as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull

    /**
     * kotlinx JsonObject is map-backed. Reject duplicate keys before parsing
     * so a hostile peer cannot exploit cross-language last-wins differences.
     * Scan bounded JSON tokens, including escaped key names and nested objects.
     * Json.parseToJsonElement then checks full syntax.
     */
    private fun hasUniqueObjectKeys(source: String): Boolean {
        data class Container(val objectType: Boolean, val names: MutableSet<String> = mutableSetOf())
        val stack = ArrayDeque<Container>()
        var index = 0
        while (index < source.length) {
            when (source[index]) {
                '{' -> stack.addLast(Container(true))
                '[' -> stack.addLast(Container(false))
                '}', ']' -> {
                    if (stack.isEmpty()) return false
                    val popped = stack.removeLast()
                    if ((source[index] == '}') != popped.objectType) return false
                }
                '"' -> {
                    val start = index
                    index++
                    var escaped = false
                    while (index < source.length) {
                        val ch = source[index]
                        if (!escaped && ch == '"') break
                        if (!escaped && ch == '\\') escaped = true
                        else escaped = false
                        index++
                    }
                    if (index >= source.length) return false
                    var next = index + 1
                    while (next < source.length && source[next].isWhitespace()) next++
                    if (next < source.length && source[next] == ':') {
                        val active = stack.lastOrNull() ?: return false
                        if (!active.objectType) return false
                        val field = try {
                            (Json.parseToJsonElement(source.substring(start, index + 1))
                                as JsonPrimitive).content
                        } catch (_: IllegalArgumentException) {
                            return false
                        }
                        if (!active.names.add(field)) return false
                    }
                }
            }
            if (stack.size > 10) return false
            index++
        }
        return stack.isEmpty()
    }
}

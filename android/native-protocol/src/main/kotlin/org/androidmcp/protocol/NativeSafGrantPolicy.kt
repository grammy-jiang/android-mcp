package org.androidmcp.protocol

import java.net.URI
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.UUID
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N4.c private, inert SAF grant model. A content URI string, an Android
 * Intent extra, or a fake approval must NEVER create a real file permission.
 */
enum class SafAccessMode { READ, WRITE }

enum class SafGrantStatus {
    SIMULATED_ONLY, DENIED, CANCELLED, STALE, EXPIRED,
    REVOKED, UNSUPPORTED, UNAVAILABLE, REPLAY_DENIED,
}

/**
 * Fakeable one-time, own-Activity picker-result metadata. The Android adapter
 * obtains the OS permission flags separately. This is NOT a public MCP input.
 *
 * Deliberately redact URI in diagnostics; document IDs can be personal data.
 */
data class SyntheticSafPickerResult(
    val apiLevel: Int,
    val processEpoch: String,
    val nonce: String,
    val launchedFromOwnPicker: Boolean,
    val action: String,
    val resultOk: Boolean,
    val contentUri: String?,
    val requestedMode: SafAccessMode,
    val grantFlags: Int,
    val osReadGranted: Boolean?,
    val osWriteGranted: Boolean?,
    val osPersistedRead: Boolean?,
    val osPersistedWrite: Boolean?,
    val userScope: String = "current",
) {
    override fun toString(): String = "SyntheticSafPickerResult([REDACTED])"
}

/** No original document URI, provider name, user, or raw grant Intent. */
data class SafGrantReceipt(
    val status: SafGrantStatus,
    val handle: String?,
    val mode: SafAccessMode?,
    val persisted: Boolean,
    val expiresAtMs: Long?,
) {
    fun metadataJson(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("synthetic_only", true)
        put("real_io_allowed", false)
        put("access_mode", mode?.name?.lowercase()?.let(::JsonPrimitive) ?: JsonNull)
        put("persisted", persisted)
        put("expires_at_elapsed_ms", expiresAtMs?.let(::JsonPrimitive) ?: JsonNull)
        // Never print the private handle in a public-style result.
    }.toString()
}

/**
 * An in-process fake result ledger for validating scoped SAF semantics.
 * It never opens ContentResolver streams or takes persistable permissions.
 *
 * An actual Android URI grant can be issued only by the platform to an
 * Activity following a user-selected document. This class is not that API.
 */
class NativeSafGrantPolicy(
    providerAuthorities: Set<String>,
    private val nowElapsedMs: () -> Long,
) : AutoCloseable {
    val processEpoch: String = UUID.randomUUID().toString()

    private data class Entry(
        val mode: SafAccessMode,
        val expires: Long,
        val selectedUriHash: ByteArray,
    )

    private val authorities = providerAuthorities
        .filter { AUTHORITY.matches(it) }
        .toSet()
    private val active = HashMap<String, Entry>()
    private val revoked = HashSet<String>()
    private val seenNonces = HashSet<String>()
    private var closed = false

    @Synchronized
    fun recognizeFake(result: SyntheticSafPickerResult): SafGrantReceipt {
        fun deny(reason: SafGrantStatus) = SafGrantReceipt(
            reason, null, null, false, null
        )
        if (closed) return deny(SafGrantStatus.REVOKED)
        if (result.processEpoch != processEpoch) return deny(SafGrantStatus.STALE)
        if (result.apiLevel !in 30..100) return deny(SafGrantStatus.UNSUPPORTED)
        if (!result.launchedFromOwnPicker ||
            result.action != ACTION_OPEN_DOCUMENT ||
            result.userScope != "current"
        ) return deny(SafGrantStatus.DENIED)
        if (!result.resultOk) return deny(SafGrantStatus.CANCELLED)
        val uri = result.contentUri
        if (uri == null || !validPickedUri(uri)) return deny(SafGrantStatus.DENIED)
        if (!NONCE.matches(result.nonce)) return deny(SafGrantStatus.DENIED)
        if (result.nonce in seenNonces) return deny(SafGrantStatus.REPLAY_DENIED)
        val flags = result.grantFlags
        if ((flags and ALLOWED_FLAGS.inv()) != 0) return deny(SafGrantStatus.DENIED)
        val access = when (result.requestedMode) {
            SafAccessMode.READ ->
                flags and FLAG_READ != 0 && result.osReadGranted == true
            SafAccessMode.WRITE ->
                flags and FLAG_WRITE != 0 && result.osWriteGranted == true
        }
        if (!access) return deny(SafGrantStatus.DENIED)
        val now = nowElapsedMs()
        if (now < 0 || now > Long.MAX_VALUE - GRANT_TTL_MS ||
            seenNonces.size >= MAX_NONCES
        ) return deny(SafGrantStatus.DENIED)
        pruneExpired(now)
        if (active.size >= MAX_ACTIVE) return deny(SafGrantStatus.UNAVAILABLE)
        val persisted = flags and FLAG_PERSISTABLE != 0 && when (result.requestedMode) {
            SafAccessMode.READ -> result.osPersistedRead == true
            SafAccessMode.WRITE -> result.osPersistedWrite == true
        }
        val handle = newHandle()
        seenNonces.add(result.nonce)
        active[handle] = Entry(
            result.requestedMode, now + GRANT_TTL_MS, uriDigest(uri),
        )
        return SafGrantReceipt(
            SafGrantStatus.SIMULATED_ONLY, handle, result.requestedMode,
            persisted, now + GRANT_TTL_MS,
        )
    }

    @Synchronized
    fun check(handle: String, mode: SafAccessMode): SafGrantStatus {
        if (closed || handle in revoked) return SafGrantStatus.REVOKED
        if (!HANDLE.matches(handle)) return SafGrantStatus.DENIED
        val entry = active[handle] ?: return SafGrantStatus.DENIED
        val now = nowElapsedMs()
        if (now < 0 || now >= entry.expires) {
            active.remove(handle)
            return SafGrantStatus.EXPIRED
        }
        if (entry.mode != mode) return SafGrantStatus.DENIED
        return SafGrantStatus.SIMULATED_ONLY
    }

    /**
     * A synthetic grant is bound to the EXACT URI selected by the fake user.
     * Same-provider aliases and differently encoded document IDs are never
     * interchangeable. No raw URI is retained, logged or exposed.
     */
    @Synchronized
    fun matchesSelectedUri(handle: String, uri: String, mode: SafAccessMode): Boolean {
        if (check(handle, mode) != SafGrantStatus.SIMULATED_ONLY ||
            !validPickedUri(uri)
        ) return false
        val entry = active[handle] ?: return false
        return MessageDigest.isEqual(entry.selectedUriHash, uriDigest(uri))
    }

    @Synchronized
    fun revoke(handle: String): Boolean {
        if (!HANDLE.matches(handle) || active.remove(handle) == null) return false
        revoked.add(handle)
        return true
    }

    @Synchronized
    fun activeCount(): Int {
        if (closed) return 0
        val now = nowElapsedMs()
        pruneExpired(now)
        return active.size
    }

    /** Even a simulated valid handle is NOT a ContentResolver permission. */
    fun realDocumentIoAllowed(): Boolean = false

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        revoked.addAll(active.keys)
        active.clear()
        seenNonces.clear()
    }

    private fun pruneExpired(now: Long) {
        if (now < 0) {
            active.clear()
            return
        }
        active.entries.removeIf { now >= it.value.expires }
    }

    private fun uriDigest(uri: String): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(uri.toByteArray(Charsets.UTF_8))

    private fun validPickedUri(text: String): Boolean {
        if (text.length !in 32..512 || text.any { it.code < 0x20 || it.code == 0x7f }) {
            return false
        }
        return try {
            val uri = URI(text)
            val authority = uri.rawAuthority ?: return false
            if (uri.scheme != "content" || authority !in authorities ||
                uri.rawUserInfo != null || uri.port != -1 ||
                uri.rawQuery != null || uri.rawFragment != null ||
                uri.host != authority
            ) return false
            val path = uri.path ?: return false
            val documentShape = path.startsWith("/document/") ||
                (path.startsWith("/tree/") && path.contains("/document/"))
            if (path.length !in 12..384 || !documentShape ||
                path.contains('\\') || path.any { it.code < 0x20 }
            ) return false
            val parts = path.split('/')
            if (parts.any { it == "." || it == ".." || it.isEmpty() && it != parts.first() }) {
                return false
            }
            val raw = uri.rawPath ?: return false
            if (raw.contains("%00", ignoreCase = true) ||
                raw.contains("%5c", ignoreCase = true) ||
                // Never accept a doubly encoded traversal or hidden path.
                raw.contains("%25", ignoreCase = true)
            ) return false
            // The SAF URI is a scoped opaque document ID. No arbitrary local
            // file path, traversal, direct filesystem access or query token.
            true
        } catch (_: Exception) {
            false
        }
    }

    companion object {
        const val ACTION_OPEN_DOCUMENT = "android.intent.action.OPEN_DOCUMENT"
        const val FLAG_READ = 1
        const val FLAG_WRITE = 2
        const val FLAG_PERSISTABLE = 64
        private const val ALLOWED_FLAGS = FLAG_READ or FLAG_WRITE or FLAG_PERSISTABLE
        private const val GRANT_TTL_MS = 60_000L
        private const val MAX_ACTIVE = 8
        private const val MAX_NONCES = 256
        private val NONCE = Regex("[A-Za-z0-9_-]{1,128}")
        private val HANDLE = Regex("[A-Za-z0-9_-]{32}")
        private val AUTHORITY = Regex("[a-z][a-z0-9.-]{2,127}")
        private val RANDOM = SecureRandom()

        private fun newHandle(): String {
            val bytes = ByteArray(24)
            RANDOM.nextBytes(bytes)
            return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        }
    }
}

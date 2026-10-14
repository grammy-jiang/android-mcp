package org.androidmcp.lifecycle

import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.channels.OverlappingFileLockException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.PosixFilePermissions
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.PublicKey
import java.security.SecureRandom
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.security.interfaces.ECPublicKey
import java.util.Base64
import java.util.UUID

/**
 * N6.a key-provider interface. Android production implementation must use
 * AndroidKeyStore: publicKey returns a PUBLIC X.509 SPKI only; sign is a
 * private-key operation, never a private-key byte-array export.
 */
interface NativeInstallationSigningProvider {
    fun createKey(alias: String): ByteArray
    fun publicKey(alias: String): ByteArray?
    fun sign(alias: String, challenge: ByteArray): ByteArray?
    fun deleteKey(alias: String)
}

/** Safe, deliberately non-secret public identity; not a pairing grant. */
data class NativePublicInstallationIdentity(
    val installationId: String,
    val verificationKeySha256: String,
    val publicKeyBase64: String,
) {
    fun encode(): String =
        "{\"schema_version\":1,\"installation_id\":\"" + installationId +
            "\",\"verification_key_sha256\":\"" + verificationKeySha256 +
            "\",\"verification_key_spki_base64\":\"" + publicKeyBase64 +
            "\",\"paired\":false,\"mutation_enabled\":false}"
}

/**
 * Persistent, app-private signing identity with exclusive process ownership.
 *
 * One fixed alias is scoped to this application, not to the device's serial,
 * MAC, IMEI or Android ID. Only a signed public identity record is persisted
 * under a private noBackupFilesDir. The key material remains in an injected
 * Keystore provider. The record signature prevents an untrusted changed
 * installationId from being accepted merely because its syntax is valid.
 *
 * This class is NOT called from public Native MCP tools or automatic startup.
 */
class NativeInstallationIdentity(
    privateRoot: Path,
    private val keys: NativeInstallationSigningProvider,
    private val nowElapsedMs: () -> Long,
) : AutoCloseable {
    val processEpoch: String = UUID.randomUUID().toString()
    private val directory = privateRoot.toAbsolutePath().normalize()
        .resolve("native-mcp-install-identity")
    private val lockPath = directory.resolve(".owner.lock")
    private val recordPath = directory.resolve("installation.v1")
    private val channel: FileChannel
    private val lock: FileLock
    private val identity: NativePublicInstallationIdentity
    private var closed = false
    private var pendingChallenge: String? = null
    private var challengeExpiresAt = 0L
    private var challengeIssuedAt = 0L

    init {
        if (!Files.isDirectory(privateRoot, LinkOption.NOFOLLOW_LINKS) ||
            Files.isSymbolicLink(privateRoot)
        ) throw IllegalStateException("NATIVE_ID_BAD_ROOT")
        var opened: FileChannel? = null
        var acquired: FileLock? = null
        try {
            if (!Files.exists(directory, LinkOption.NOFOLLOW_LINKS)) {
                Files.createDirectory(directory, DIR_MODE)
            }
            if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) ||
                Files.isSymbolicLink(directory)
            ) throw IllegalStateException("NATIVE_ID_BAD_DIRECTORY")
            Files.setPosixFilePermissions(directory, DIR_PERMISSIONS)
            if (Files.isSymbolicLink(lockPath)) throw IllegalStateException("NATIVE_ID_BAD_LOCK")
            opened = FileChannel.open(
                lockPath, StandardOpenOption.CREATE, StandardOpenOption.READ,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS,
            )
            Files.setPosixFilePermissions(lockPath, FILE_PERMISSIONS)
            acquired = try {
                opened.tryLock()
            } catch (_: OverlappingFileLockException) {
                null
            }
            if (acquired == null) throw IllegalStateException("NATIVE_ID_BUSY")
            // Recovery is fail-closed if an orphaned staging file cannot be
            // removed. An existing committed record is never overwritten by
            // an invalid/corrupted file.
            Files.newDirectoryStream(directory, ".identity-*.tmp").use { files ->
                files.forEach { path ->
                    if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
                        throw IllegalStateException("NATIVE_ID_BAD_STAGING")
                    }
                    Files.delete(path)
                }
            }
            identity = if (Files.exists(recordPath, LinkOption.NOFOLLOW_LINKS)) {
                load()
            } else create()
            channel = opened
            lock = acquired
        } catch (_: Exception) {
            try { acquired?.release() } catch (_: Exception) { /* deny */ }
            try { opened?.close() } catch (_: Exception) { /* deny */ }
            throw IllegalStateException("NATIVE_ID_UNAVAILABLE")
        }
    }

    @Synchronized
    fun publicIdentity(): NativePublicInstallationIdentity {
        ensureOpen()
        return identity
    }

    /**
     * Ephemeral synthetic challenge is never restored after process restart,
     * FGS death or owner close. It is not a public pairing route.
     */
    @Synchronized
    fun beginSyntheticChallenge(): String {
        ensureOpen()
        val now = nowElapsedMs()
        if (now < 0 || now > Long.MAX_VALUE - CHALLENGE_TTL_MS) {
            throw IllegalStateException("NATIVE_ID_CLOCK_UNAVAILABLE")
        }
        val bytes = ByteArray(24)
        RANDOM.nextBytes(bytes)
        val value = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        pendingChallenge = value
        challengeIssuedAt = now
        challengeExpiresAt = now + CHALLENGE_TTL_MS
        return value
    }

    @Synchronized
    fun verifySyntheticProof(challenge: String, signature: ByteArray): Boolean {
        if (closed) return false
        val expected = pendingChallenge ?: return false
        pendingChallenge = null // consume on first attempt, even if forged
        val now = nowElapsedMs()
        if (now < challengeIssuedAt || now > challengeExpiresAt ||
            challenge != expected || signature.size !in 8..256
        ) return false
        return try {
            verifySignature(
                decodePublic(identity.publicKeyBase64),
                challenge.toByteArray(Charsets.US_ASCII),
                signature,
            )
        } catch (_: Exception) {
            false
        }
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        pendingChallenge = null
        try { lock.release() } catch (_: Exception) { /* deny */ }
        try { channel.close() } catch (_: Exception) { /* deny */ }
    }

    private fun ensureOpen() {
        if (closed) throw IllegalStateException("NATIVE_ID_CLOSED")
    }

    private fun create(): NativePublicInstallationIdentity {
        // On a simulated uninstall/data-clear the private file disappears.
        // Remove an orphan key *only while holding this process's OS lock*
        // before creating a fresh key. Do not delete it on corrupt records.
        try {
            keys.deleteKey(KEY_ALIAS)
            val spki = keys.createKey(KEY_ALIAS)
            val publicKey = parsePublic(spki)
            val canonical = publicKey.encoded
            if (!MessageDigest.isEqual(canonical, spki)) {
                throw IllegalStateException("NATIVE_ID_NONCANONICAL_SPKI")
            }
            val installId = UUID.randomUUID().toString()
            val fingerprint = sha256(spki)
            val payload = "N6A1|$installId|$fingerprint"
            val signature = keys.sign(KEY_ALIAS, payload.toByteArray(Charsets.US_ASCII))
                ?: throw IllegalStateException("NATIVE_ID_SIGN_FAILED")
            if (!verifySignature(publicKey, payload.toByteArray(Charsets.US_ASCII), signature)) {
                throw IllegalStateException("NATIVE_ID_BAD_SIGNATURE")
            }
            val record = payload + "|" +
                Base64.getUrlEncoder().withoutPadding().encodeToString(signature) + "\n"
            save(record)
            return NativePublicInstallationIdentity(
                installId, fingerprint, Base64.getEncoder().encodeToString(spki),
            )
        } catch (_: Exception) {
            try { keys.deleteKey(KEY_ALIAS) } catch (_: Exception) { /* deny */ }
            throw IllegalStateException("NATIVE_ID_CREATE_FAILED")
        }
    }

    private fun load(): NativePublicInstallationIdentity {
        if (!Files.isRegularFile(recordPath, LinkOption.NOFOLLOW_LINKS) ||
            Files.isSymbolicLink(recordPath) ||
            Files.size(recordPath) !in 20..MAX_RECORD_BYTES.toLong()
        ) throw IllegalStateException("NATIVE_ID_INVALID_RECORD")
        // Android ART API 30–36 does not provide java.nio.file.Files.readString
        // even when Gradle compiles against JDK 17. Check size both before and
        // after read to fail closed on a changed/corrupted private record.
        val encoded = Files.readAllBytes(recordPath)
        if (encoded.size !in 20..MAX_RECORD_BYTES) {
            throw IllegalStateException("NATIVE_ID_INVALID_RECORD_SIZE")
        }
        val record = String(encoded, Charsets.US_ASCII)
        if (!record.endsWith('\n')) throw IllegalStateException("NATIVE_ID_TRUNCATED")
        val parts = record.trimEnd('\n').split('|')
        if (parts.size != 4 || parts[0] != "N6A1" ||
            !UUID_REGEX.matches(parts[1]) || !SHA_REGEX.matches(parts[2])
        ) throw IllegalStateException("NATIVE_ID_INVALID_RECORD")
        val spki = keys.publicKey(KEY_ALIAS) ?: throw IllegalStateException("NATIVE_ID_KEY_MISSING")
        val public = parsePublic(spki)
        if (!MessageDigest.isEqual(public.encoded, spki) || sha256(spki) != parts[2]) {
            throw IllegalStateException("NATIVE_ID_KEY_MISMATCH")
        }
        val signature = Base64.getUrlDecoder().decode(parts[3])
        if (signature.size !in 8..256 ||
            !verifySignature(
                public, parts.take(3).joinToString("|").toByteArray(Charsets.US_ASCII),
                signature,
            )
        ) throw IllegalStateException("NATIVE_ID_SIGNATURE_INVALID")
        return NativePublicInstallationIdentity(
            parts[1], parts[2], Base64.getEncoder().encodeToString(spki),
        )
    }

    private fun save(data: String) {
        val bytes = data.toByteArray(Charsets.US_ASCII)
        if (bytes.size > MAX_RECORD_BYTES || Files.exists(recordPath, LinkOption.NOFOLLOW_LINKS)) {
            throw IllegalStateException("NATIVE_ID_WRITE_REFUSED")
        }
        var staging: Path? = null
        try {
            staging = Files.createTempFile(directory, ".identity-", ".tmp", FILE_MODE)
            FileChannel.open(
                staging, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS,
            ).use { output ->
                val buffer = ByteBuffer.wrap(bytes)
                while (buffer.hasRemaining()) output.write(buffer)
                output.force(true)
            }
            Files.move(
                staging, recordPath, StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
            staging = null
            Files.setPosixFilePermissions(recordPath, FILE_PERMISSIONS)
        } catch (_: Exception) {
            throw IllegalStateException("NATIVE_ID_COMMIT_FAILED")
        } finally {
            try { staging?.let(Files::deleteIfExists) } catch (_: Exception) { /* deny */ }
        }
    }

    companion object {
        const val KEY_ALIAS = "android-mcp-native-install-signing-v1"
        private const val CHALLENGE_TTL_MS = 30_000L
        private const val MAX_RECORD_BYTES = 2048
        private val UUID_REGEX = Regex("[a-f0-9-]{36}")
        private val SHA_REGEX = Regex("[a-f0-9]{64}")
        private val RANDOM = SecureRandom()
        private val DIR_PERMISSIONS = PosixFilePermissions.fromString("rwx------")
        private val FILE_PERMISSIONS = PosixFilePermissions.fromString("rw-------")
        private val DIR_MODE = PosixFilePermissions.asFileAttribute(DIR_PERMISSIONS)
        private val FILE_MODE = PosixFilePermissions.asFileAttribute(FILE_PERMISSIONS)

        private fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes)
                .joinToString("") { "%02x".format(it) }

        private fun parsePublic(spki: ByteArray): PublicKey {
            if (spki.size !in 60..300) throw IllegalStateException("NATIVE_ID_KEY_SIZE")
            val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(spki))
            if (key !is ECPublicKey || key.params.curve.field.fieldSize != 256) {
                throw IllegalStateException("NATIVE_ID_KEY_ALGORITHM")
            }
            return key
        }

        private fun decodePublic(base64: String) =
            parsePublic(Base64.getDecoder().decode(base64))

        private fun verifySignature(key: PublicKey, data: ByteArray, sig: ByteArray): Boolean =
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(key)
                update(data)
                verify(sig)
            }
    }
}

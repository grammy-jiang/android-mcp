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
import java.security.MessageDigest

/**
 * N6.c inert persistent synthetic lease high-water, NOT a mutation authority.
 */
enum class FenceStatus {
    SYNTHETIC_RECOGNIZED, DENIED, STALE, DUPLICATE, REPLAY,
    PAIRING_REQUIRED, EXPIRED, CLOCK_ROLLBACK, UNCERTAIN, BUSY, STOPPED,
}

data class SyntheticFenceRequest(
    val nativeInstallation: String,
    val bootEpoch: String,
    val hostIdentity: String,
    val fence: Long,
    val planDigest: String,
    val nonce: String,
    val expiresAtElapsedMs: Long,
    val fakeHostProofAccepted: Boolean,
) {
    override fun toString() = "SyntheticFenceRequest([REDACTED])"
}
data class FenceReceipt(val status: FenceStatus, val recordedHighWater: Long?) {
    fun encode(): String =
        "{\"schema_version\":1,\"status\":\"" + status.name.lowercase() +
            "\",\"synthetic_only\":true,\"mutation_executed\":false}"
}

/**
 * Own-app private journal locked against simultaneous FGS process owners.
 *
 * A successful fake fence is returned only AFTER atomic journal publication.
 * Process crash after publication but before receipt is uncertain; restart
 * preserves the highest fence and refuses duplicate execution.
 *
 * Unlike a real lease broker this journal is NOT hardware-key authenticated.
 * It cannot authorize real Android/Host mutations and never connects to MCP.
 */
class NativeFenceState(
    privateRoot: Path,
    private val nativeInstallation: String,
    private val bootEpoch: String,
    private val hostIdentity: String,
    private val elapsedClock: () -> Long,
    private val beforeCommit: () -> Unit = {},
) : AutoCloseable {
    private val dir = privateRoot.toAbsolutePath().normalize().resolve("native-mcp-fencing")
    private val path = dir.resolve("fence.v1")
    private val lockPath = dir.resolve(".owner.lock")
    private val channel: FileChannel
    private val lock: FileLock
    private var storedInstall = nativeInstallation
    private var storedBoot = bootEpoch
    private var storedHost = hostIdentity
    private var water = 0L
    private var latestElapsed = -1L
    private val digests = ArrayDeque<String>()
    private val nonces = ArrayDeque<String>()
    private var closed = false
    private var faulted = false
    private var active = false

    init {
        if (!Files.isDirectory(privateRoot, LinkOption.NOFOLLOW_LINKS) ||
            Files.isSymbolicLink(privateRoot)
        ) throw IllegalStateException("FENCE_BAD_ROOT")
        var opened: FileChannel? = null
        var acquired: FileLock? = null
        try {
            if (!Files.exists(dir, LinkOption.NOFOLLOW_LINKS)) {
                Files.createDirectory(dir, DIR_MODE)
            }
            if (!Files.isDirectory(dir, LinkOption.NOFOLLOW_LINKS) ||
                Files.isSymbolicLink(dir)
            ) throw IllegalStateException("FENCE_BAD_DIR")
            Files.setPosixFilePermissions(dir, DIR_PERMISSIONS)
            if (Files.isSymbolicLink(lockPath)) throw IllegalStateException("FENCE_BAD_LOCK")
            opened = FileChannel.open(
                lockPath, StandardOpenOption.CREATE, StandardOpenOption.READ,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS,
            )
            Files.setPosixFilePermissions(lockPath, FILE_PERMISSIONS)
            acquired = try { opened.tryLock() } catch (_: OverlappingFileLockException) { null }
            if (acquired == null) throw IllegalStateException("FENCE_BUSY")
            // Previous crashed staging files have never been committed.
            Files.newDirectoryStream(dir, ".fence-*.tmp").use { files ->
                files.forEach { file ->
                    if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) {
                        throw IllegalStateException("FENCE_BAD_STAGING")
                    }
                    Files.delete(file)
                }
            }
            if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) load()
            channel = opened
            lock = acquired
        } catch (_: Exception) {
            try { acquired?.release() } catch (_: Exception) { /* deny */ }
            try { opened?.close() } catch (_: Exception) { /* deny */ }
            throw IllegalStateException("FENCE_UNAVAILABLE")
        }
    }

    @Synchronized
    fun issue(request: SyntheticFenceRequest): FenceReceipt {
        fun result(status: FenceStatus, high: Long? = null) = FenceReceipt(status, high)
        if (closed) return result(FenceStatus.STOPPED)
        if (faulted) return result(FenceStatus.UNCERTAIN)
        val current = elapsedClock()
        if (current < 0 || (latestElapsed >= 0 && current < latestElapsed)) {
            active = false
            return result(FenceStatus.CLOCK_ROLLBACK)
        }
        if (storedInstall != nativeInstallation ||
            storedBoot != bootEpoch || storedHost != hostIdentity
        ) return result(FenceStatus.PAIRING_REQUIRED)
        if (request.nativeInstallation != nativeInstallation ||
            request.bootEpoch != bootEpoch ||
            request.hostIdentity != hostIdentity ||
            !request.fakeHostProofAccepted ||
            !IDENT.matches(request.hostIdentity) ||
            !IDENT.matches(request.nativeInstallation) ||
            !IDENT.matches(request.bootEpoch) ||
            !DIGEST.matches(request.planDigest) ||
            !NONCE.matches(request.nonce)
        ) return result(FenceStatus.DENIED)
        if (request.expiresAtElapsedMs <= current ||
            request.expiresAtElapsedMs - current > MAX_TTL_MS
        ) return result(FenceStatus.EXPIRED)
        if (request.fence <= water) return result(FenceStatus.STALE)
        val nonceDigest = sha256(request.nonce)
        if (nonceDigest in nonces) return result(FenceStatus.REPLAY)
        if (request.planDigest in digests) return result(FenceStatus.DUPLICATE)
        if (water == Long.MAX_VALUE) return result(FenceStatus.STALE)

        val newNonces = ArrayDeque(nonces)
        val newDigests = ArrayDeque(digests)
        if (newNonces.size >= MAX_REMEMBERED) newNonces.removeFirst()
        if (newDigests.size >= MAX_REMEMBERED) newDigests.removeFirst()
        newNonces.addLast(nonceDigest)
        newDigests.addLast(request.planDigest)
        if (!persist(request.fence, current, newDigests, newNonces)) {
            faulted = true
            active = false
            return result(FenceStatus.UNCERTAIN)
        }
        water = request.fence
        latestElapsed = current
        nonces.clear()
        nonces.addAll(newNonces)
        digests.clear()
        digests.addAll(newDigests)
        active = true
        return result(FenceStatus.SYNTHETIC_RECOGNIZED, water)
    }

    @Synchronized
    fun highWater(): Long = water

    @Synchronized
    fun fakeLeaseActive(): Boolean = active && !closed && !faulted

    /** Synthetic proof is never a real Android mutating-operation grant. */
    fun realMutationAllowed(): Boolean = false

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        active = false
        try { lock.release() } catch (_: Exception) { /* deny */ }
        try { channel.close() } catch (_: Exception) { /* deny */ }
    }

    private fun persist(
        nextWater: Long, whenElapsed: Long,
        nextDigests: ArrayDeque<String>,
        nextNonces: ArrayDeque<String>,
    ): Boolean {
        val header = listOf(
            "N6C1", storedInstall, storedBoot, storedHost,
            nextWater.toString(), whenElapsed.toString(),
        ).joinToString("|")
        val lines = buildString {
            append(header).append('\n')
            nextDigests.forEach { append("D|").append(it).append('\n') }
            nextNonces.forEach { append("N|").append(it).append('\n') }
        }
        val serialized = lines + "C|" + sha256(lines) + "\n"
        val bytes = serialized.toByteArray(Charsets.US_ASCII)
        if (bytes.size > MAX_FILE_BYTES) return false
        var staging: Path? = null
        return try {
            if (Files.isSymbolicLink(path)) return false
            staging = Files.createTempFile(dir, ".fence-", ".tmp", FILE_MODE)
            FileChannel.open(
                staging, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS,
            ).use { output ->
                val buffer = ByteBuffer.wrap(bytes)
                while (buffer.hasRemaining()) output.write(buffer)
                output.force(true)
            }
            beforeCommit()
            Files.move(
                staging, path, StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
            staging = null
            Files.setPosixFilePermissions(path, FILE_PERMISSIONS)
            true
        } catch (_: Exception) {
            false
        } finally {
            try { staging?.let(Files::deleteIfExists) } catch (_: Exception) { /* deny */ }
        }
    }

    private fun load() {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) ||
            Files.isSymbolicLink(path) || Files.size(path) !in 30..MAX_FILE_BYTES.toLong()
        ) throw IllegalStateException("FENCE_CORRUPT")
        val content = Files.readString(path, Charsets.US_ASCII)
        val lines = content.lines().filter { it.isNotEmpty() }
        val checksum = lines.lastOrNull()?.split('|') ?: throw IllegalStateException()
        if (checksum.size != 2 || checksum[0] != "C" ||
            !DIGEST.matches(checksum[1])
        ) throw IllegalStateException()
        val payload = lines.dropLast(1).joinToString("\n", postfix = "\n")
        if (sha256(payload) != checksum[1]) throw IllegalStateException()
        val header = lines.first().split('|')
        if (header.size != 6 || header[0] != "N6C1" ||
            !IDENT.matches(header[1]) || !IDENT.matches(header[2]) ||
            !IDENT.matches(header[3])
        ) throw IllegalStateException()
        storedInstall = header[1]
        storedBoot = header[2]
        storedHost = header[3]
        water = header[4].toLong()
        latestElapsed = header[5].toLong()
        if (water < 0 || latestElapsed < 0) throw IllegalStateException()
        lines.drop(1).dropLast(1).forEach { line ->
            val entry = line.split('|')
            if (entry.size != 2 || !DIGEST.matches(entry[1])) {
                throw IllegalStateException()
            }
            when (entry[0]) {
                "D" -> digests.addLast(entry[1])
                "N" -> nonces.addLast(entry[1])
                else -> throw IllegalStateException()
            }
        }
        if (digests.size != nonces.size ||
            digests.size !in 0..MAX_REMEMBERED
        ) throw IllegalStateException()
    }

    companion object {
        private const val MAX_TTL_MS = 30_000L
        private const val MAX_REMEMBERED = 32
        private const val MAX_FILE_BYTES = 8192
        private val IDENT = Regex("[A-Za-z0-9_-]{8,128}")
        private val NONCE = Regex("[A-Za-z0-9_-]{1,128}")
        private val DIGEST = Regex("[a-f0-9]{64}")
        private val DIR_PERMISSIONS = PosixFilePermissions.fromString("rwx------")
        private val FILE_PERMISSIONS = PosixFilePermissions.fromString("rw-------")
        private val DIR_MODE = PosixFilePermissions.asFileAttribute(DIR_PERMISSIONS)
        private val FILE_MODE = PosixFilePermissions.asFileAttribute(FILE_PERMISSIONS)

        private fun sha256(value: String): String =
            MessageDigest.getInstance("SHA-256")
                .digest(value.toByteArray(Charsets.US_ASCII))
                .joinToString("") { "%02x".format(it) }
    }
}

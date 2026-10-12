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
import java.security.SecureRandom
import java.util.Base64

/**
 * Only fixed error codes cross the boundary. Never chain an IOException
 * containing a sensitive application path or capture bytes into MCP output.
 */
enum class ArtifactFailureCode {
    INVALID_ROOT, BUSY, INVALID_HANDLE, TOO_LARGE, CAPACITY, IO_FAILURE, CLOSED, BAD_INPUT
}

class ArtifactFailure(val code: ArtifactFailureCode) : RuntimeException(code.name)

/** Internal handle metadata only: actual artifact data never enters a Tool result. */
data class NativeArtifactReceipt(
    val handle: String,
    val mimeType: String,
    val sizeBytes: Int,
    val sha256: String,
    val createdAtMs: Long,
    val expiresAtMs: Long,
)

/**
 * App-private, single-owner, bounded Native artifact store for later user-
 * consented capture/SAF work. This is NOT an HTTP resource or public MCP Tool.
 *
 * The caller must supply Android Context.noBackupFilesDir (or a private
 * isolated test dir). Initialization holds an OS file lock; a later process
 * reclaims stale partial/complete files only when no live owner holds it.
 * Handles exist only in memory and are invalidated on process restart.
 */
class NativeArtifactStore(
    privateRoot: Path,
    private val clock: () -> Long = System::currentTimeMillis,
    private val ttlMs: Long = 300_000,
    private val maxArtifactBytes: Int = 8 * 1024 * 1024,
    private val maxTotalBytes: Long = 32L * 1024 * 1024,
    private val maxEntries: Int = 16,
    private val handleGenerator: () -> String = ::randomHandle,
    private val writeStaging: ((Path, ByteArray) -> Unit)? = null,
    private val beforeCommit: () -> Unit = {},
) : AutoCloseable {
    private val directory = privateRoot.toAbsolutePath().normalize()
        .resolve("native-mcp-artifacts")
    private val ownerLockPath = directory.resolve(".owner.lock")
    private val channel: FileChannel
    private val ownerLock: FileLock
    private val entries = linkedMapOf<String, NativeArtifactReceipt>()
    private var closed = false

    init {
        require(ttlMs in 1..900_000 && maxArtifactBytes in 1..(16 * 1024 * 1024))
        require(maxTotalBytes in maxArtifactBytes.toLong()..(64L * 1024 * 1024))
        require(maxEntries in 1..64)
        if (!Files.isDirectory(privateRoot, LinkOption.NOFOLLOW_LINKS) ||
            Files.isSymbolicLink(privateRoot)
        ) throw ArtifactFailure(ArtifactFailureCode.INVALID_ROOT)

        var opened: FileChannel? = null
        var acquired: FileLock? = null
        try {
            if (!Files.exists(directory, LinkOption.NOFOLLOW_LINKS)) {
                Files.createDirectory(directory, DIR_MODE)
            }
            if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) ||
                Files.isSymbolicLink(directory)
            ) throw ArtifactFailure(ArtifactFailureCode.INVALID_ROOT)
            Files.setPosixFilePermissions(directory, DIR_PERMISSIONS)
            if (!Files.exists(ownerLockPath, LinkOption.NOFOLLOW_LINKS)) {
                Files.createFile(ownerLockPath, FILE_MODE)
            }
            if (!Files.isRegularFile(ownerLockPath, LinkOption.NOFOLLOW_LINKS)) {
                throw ArtifactFailure(ArtifactFailureCode.INVALID_ROOT)
            }
            Files.setPosixFilePermissions(ownerLockPath, FILE_PERMISSIONS)
            opened = FileChannel.open(
                ownerLockPath,
                StandardOpenOption.READ, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS
            )
            acquired = try {
                opened.tryLock()
            } catch (_: OverlappingFileLockException) {
                null
            }
            if (acquired == null) throw ArtifactFailure(ArtifactFailureCode.BUSY)
            // Never trust a previous process's metadata or partially written
            // artifact. After owner takeover, purge all leftovers fail-closed.
            purgeFilesFromDisk()
            channel = opened
            ownerLock = acquired
        } catch (error: Exception) {
            try { acquired?.release() } catch (_: Exception) { /* fail closed */ }
            try { opened?.close() } catch (_: Exception) { /* fail closed */ }
            if (error is ArtifactFailure) throw error
            throw ArtifactFailure(ArtifactFailureCode.IO_FAILURE)
        }
    }

    @Synchronized
    fun create(bytes: ByteArray, mimeType: String): NativeArtifactReceipt {
        requireOpen()
        if (bytes.isEmpty() || !MIME.matches(mimeType)) {
            throw ArtifactFailure(ArtifactFailureCode.BAD_INPUT)
        }
        if (bytes.size > maxArtifactBytes) {
            throw ArtifactFailure(ArtifactFailureCode.TOO_LARGE)
        }
        purgeExpired()
        if (entries.size >= maxEntries ||
            entries.values.sumOf { it.sizeBytes.toLong() } + bytes.size > maxTotalBytes
        ) throw ArtifactFailure(ArtifactFailureCode.CAPACITY)

        val stableBytes = bytes.copyOf()
        val timestamp = clock()
        if (timestamp < 0 || timestamp > Long.MAX_VALUE - ttlMs) {
            throw ArtifactFailure(ArtifactFailureCode.BAD_INPUT)
        }
        val handle = handleGenerator()
        if (!HANDLE.matches(handle) || entries.containsKey(handle)) {
            throw ArtifactFailure(ArtifactFailureCode.INVALID_HANDLE)
        }

        var staging: Path? = null
        var destinationReserved = false
        val destination = directory.resolve(handle)
        try {
            staging = Files.createTempFile(directory, ".pending-", ".tmp", FILE_MODE)
            if (writeStaging == null) writePrivateStaging(staging, stableBytes)
            else writeStaging.invoke(staging, stableBytes)
            if (Files.size(staging) != stableBytes.size.toLong()) {
                throw ArtifactFailure(ArtifactFailureCode.IO_FAILURE)
            }
            val staged = Files.newInputStream(staging, LinkOption.NOFOLLOW_LINKS).use {
                it.readNBytes(stableBytes.size + 1)
            }
            if (staged.size != stableBytes.size || sha256(staged) != sha256(stableBytes)) {
                throw ArtifactFailure(ArtifactFailureCode.IO_FAILURE)
            }

            // CREATE_NEW is a filesystem-level collision guard, even if a
            // second (incorrectly running) same-UID process ignores the lock.
            Files.createFile(destination, FILE_MODE)
            destinationReserved = true
            beforeCommit()
            Files.move(
                staging, destination, StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING
            )
            staging = null
            val receipt = NativeArtifactReceipt(
                handle = handle,
                mimeType = mimeType,
                sizeBytes = bytes.size,
                sha256 = sha256(stableBytes),
                createdAtMs = timestamp,
                expiresAtMs = timestamp + ttlMs,
            )
            entries[handle] = receipt
            return receipt
        } catch (_: Exception) {
            // No receipt was published. Never echo IO/platform exception data.
            if (destinationReserved) deleteQuietly(destination)
            throw ArtifactFailure(ArtifactFailureCode.IO_FAILURE)
        } finally {
            staging?.let(::deleteQuietly)
        }
    }

    @Synchronized
    fun read(handle: String): ByteArray? {
        requireOpen()
        if (!HANDLE.matches(handle)) return null
        val receipt = entries[handle] ?: return null
        if (clock() >= receipt.expiresAtMs) {
            remove(handle)
            return null
        }
        val file = directory.resolve(handle)
        return try {
            if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) ||
                Files.size(file) != receipt.sizeBytes.toLong()
            ) {
                remove(handle)
                null
            } else {
                val bytes = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS).use {
                    it.readNBytes(receipt.sizeBytes + 1)
                }
                if (bytes.size != receipt.sizeBytes || sha256(bytes) != receipt.sha256) {
                    remove(handle)
                    null
                } else bytes
            }
        } catch (_: Exception) {
            entries.remove(handle)
            deleteQuietly(file)
            null
        }
    }

    @Synchronized
    fun remove(handle: String): Boolean {
        requireOpen()
        if (!HANDLE.matches(handle) || entries.remove(handle) == null) return false
        val destination = directory.resolve(handle)
        try {
            Files.deleteIfExists(destination)
        } catch (_: Exception) {
            throw ArtifactFailure(ArtifactFailureCode.IO_FAILURE)
        }
        return true
    }

    @Synchronized
    fun purgeExpired(): Int {
        requireOpen()
        val now = clock()
        val expired = entries.values.filter { now >= it.expiresAtMs }.map { it.handle }
        expired.forEach(::remove)
        return expired.size
    }

    @Synchronized
    fun activeCount(): Int {
        requireOpen()
        return entries.size
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        entries.clear()
        var cleanupFailed = false
        try {
            purgeFilesFromDisk()
        } catch (_: Exception) {
            cleanupFailed = true
        } finally {
            try {
                ownerLock.release()
                channel.close()
            } catch (_: Exception) {
                cleanupFailed = true
            }
        }
        if (cleanupFailed) throw ArtifactFailure(ArtifactFailureCode.IO_FAILURE)
    }

    private fun requireOpen() {
        if (closed) throw ArtifactFailure(ArtifactFailureCode.CLOSED)
    }

    private fun purgeFilesFromDisk() {
        Files.newDirectoryStream(directory).use { stream ->
            for (file in stream) {
                if (file.fileName.toString() == ownerLockPath.fileName.toString()) continue
                if (Files.isDirectory(file, LinkOption.NOFOLLOW_LINKS)) {
                    throw ArtifactFailure(ArtifactFailureCode.INVALID_ROOT)
                }
                Files.deleteIfExists(file) // deleting symlinks never follows targets
            }
        }
    }

    private fun writePrivateStaging(path: Path, bytes: ByteArray) {
        FileChannel.open(
            path, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING,
            LinkOption.NOFOLLOW_LINKS
        ).use { channel ->
            val buffer = ByteBuffer.wrap(bytes)
            while (buffer.hasRemaining()) channel.write(buffer)
            channel.force(true)
        }
    }

    private fun deleteQuietly(path: Path) {
        try {
            Files.deleteIfExists(path)
        } catch (_: Exception) {
            // A failed cleanup remains in the app-private owner directory.
            // A new store owner purges untrusted files on restart.
        }
    }

    companion object {
        private val HANDLE = Regex("[A-Za-z0-9_-]{32}")
        private val MIME = Regex("[a-z0-9.+_-]{1,64}/[a-z0-9.+_-]{1,64}")
        private val RANDOM = SecureRandom()
        private val DIR_PERMISSIONS = PosixFilePermissions.fromString("rwx------")
        private val FILE_PERMISSIONS = PosixFilePermissions.fromString("rw-------")
        private val DIR_MODE = PosixFilePermissions.asFileAttribute(DIR_PERMISSIONS)
        private val FILE_MODE = PosixFilePermissions.asFileAttribute(FILE_PERMISSIONS)

        private fun randomHandle(): String {
            val bytes = ByteArray(24)
            RANDOM.nextBytes(bytes)
            return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        }

        private fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes)
                .joinToString("") { "%02x".format(it) }
    }
}

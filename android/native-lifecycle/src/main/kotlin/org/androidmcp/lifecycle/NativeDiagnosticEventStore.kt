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
import java.util.ArrayDeque
import java.util.Base64
import java.util.UUID

/**
 * N5.c finite, own-process diagnostic event codes only.
 *
 * This is NOT an MCP subscription, OS Logcat reader or user data collection
 * endpoint. No event message, stacktrace, package/user ID, account or raw
 * nonce is persisted. The private journal stores bounded numeric codes and
 * SHA-256 nonce digests under an OS-owner file lock.
 */
enum class OwnEventOrigin { ACTIVITY, FOREGROUND_SERVICE, APPLICATION }
enum class OwnEventSensitivity { COARSE, REDACTED_PRIVATE }
enum class OwnEventKind { STARTED, STOPPED, CRASH, ANR, PERMISSION_REFUSED }
enum class OwnEventState {
    APPENDED, DUPLICATE, DENIED, UNAVAILABLE, STOPPED, BUSY, CORRUPT,
}
enum class OwnEventPageState { AVAILABLE, EMPTY, DENIED, GAP, STOPPED, UNCERTAIN }
enum class OwnEventAckState { ACKNOWLEDGED, ALREADY_ACKED, DENIED, STOPPED }

data class OwnDiagnosticEvent(
    val id: Long,
    val elapsedMs: Long,
    val origin: OwnEventOrigin,
    val sensitivity: OwnEventSensitivity,
    val kind: OwnEventKind,
)

data class OwnEventAppendResult(
    val state: OwnEventState,
    val event: OwnDiagnosticEvent? = null,
)

data class OwnEventPage(
    val state: OwnEventPageState,
    val events: List<OwnDiagnosticEvent> = emptyList(),
    val nextCursor: String? = null,
    val droppedOverflow: Long = 0,
    val droppedExpired: Long = 0,
) {
    /** One small, explicitly uncertainty-labelled synthetic result. */
    fun encode(): String = buildString {
        append("{\"schema_version\":1,\"status\":\"")
        append(state.name.lowercase())
        append("\",\"synthetic_only\":true,\"subscriber_delivery_confirmed\":false,")
        append("\"dropped_overflow\":").append(droppedOverflow)
        append(",\"dropped_expired\":").append(droppedExpired)
        append(",\"events\":[")
        events.forEachIndexed { index, event ->
            if (index > 0) append(',')
            append("{\"id\":").append(event.id)
            append(",\"sampled_elapsed_ms\":").append(event.elapsedMs)
            append(",\"origin\":\"").append(event.origin.name.lowercase()).append('"')
            append(",\"sensitivity\":\"").append(event.sensitivity.name.lowercase()).append('"')
            append(",\"code\":\"").append(event.kind.name.lowercase()).append("\"}")
        }
        append("]}")
        // Only fixed enum labels and bounded numbers, no user text/cursors.
    }

}

/**
 * Durable, owner-locked event queue for app-private storage only.
 *
 * File format is a small fixed ASCII journal; every mutation atomically
 * replaces the prior journal after writing/fsync of a private staging file.
 * A crashed writer cannot retroactively claim delivery: unacknowledged
 * events remain pending and are marked UNCERTAIN on the next owner.
 *
 * The fake subscriber token is not real authentication: it is never
 * derived from untrusted HTTP, Origin, an ADB serial or MCP arguments.
 */
class NativeDiagnosticEventStore(
    privateRoot: Path,
    private val clockElapsedMs: () -> Long,
) : AutoCloseable {
    val processEpoch: String = UUID.randomUUID().toString()

    private data class Entry(
        val value: OwnDiagnosticEvent,
        val nonceHash: String,
    )
    private val dir: Path = privateRoot.toAbsolutePath().normalize()
        .resolve("native-mcp-events")
    private val journal = dir.resolve("events.v1")
    private val ownerFile = dir.resolve(".owner.lock")
    private val channel: FileChannel
    private val lock: FileLock
    private val records = ArrayDeque<Entry>()
    private val seenNonces = ArrayDeque<String>()
    private var nextId = 1L
    private var ackedThrough = 0L
    private var lastElapsed = -1L
    private var droppedOverflow = 0L
    private var droppedExpired = 0L
    private var recoveredUnacked = false
    private var stopped = false
    private var faulted = false

    private var subscriberToken: String? = null
    private var issuedThrough = 0L
    private var lastCursor: String? = null
    private var afterCursor = 0L

    init {
        if (!Files.isDirectory(privateRoot, LinkOption.NOFOLLOW_LINKS) ||
            Files.isSymbolicLink(privateRoot)
        ) throw IllegalStateException("NATIVE_EVENTS_BAD_ROOT")

        var opened: FileChannel? = null
        var acquired: FileLock? = null
        try {
            if (!Files.exists(dir, LinkOption.NOFOLLOW_LINKS)) {
                Files.createDirectory(dir, DIR_MODE)
            }
            if (!Files.isDirectory(dir, LinkOption.NOFOLLOW_LINKS) ||
                Files.isSymbolicLink(dir)
            ) throw IllegalStateException("NATIVE_EVENTS_BAD_ROOT")
            Files.setPosixFilePermissions(dir, DIR_PERMISSIONS)
            if (Files.isSymbolicLink(ownerFile)) {
                throw IllegalStateException("NATIVE_EVENTS_BAD_LOCK")
            }
            opened = FileChannel.open(
                ownerFile,
                StandardOpenOption.CREATE,
                StandardOpenOption.READ,
                StandardOpenOption.WRITE,
                LinkOption.NOFOLLOW_LINKS,
            )
            Files.setPosixFilePermissions(ownerFile, FILE_PERMISSIONS)
            acquired = try {
                opened.tryLock()
            } catch (_: OverlappingFileLockException) {
                null
            }
            if (acquired == null) throw IllegalStateException("NATIVE_EVENTS_BUSY")
            loadJournal()
            purgeStaleStaging()
            recoveredUnacked = records.isNotEmpty()
            channel = opened
            lock = acquired
        } catch (_: Exception) {
            try { acquired?.release() } catch (_: Exception) { /* no leak */ }
            try { opened?.close() } catch (_: Exception) { /* no leak */ }
            throw IllegalStateException("NATIVE_EVENTS_UNAVAILABLE")
        }
    }

    @Synchronized
    fun append(
        nonce: String,
        origin: OwnEventOrigin,
        kind: OwnEventKind,
        sensitivity: OwnEventSensitivity = OwnEventSensitivity.COARSE,
    ): OwnEventAppendResult {
        if (stopped) return OwnEventAppendResult(OwnEventState.STOPPED)
        if (faulted) return OwnEventAppendResult(OwnEventState.UNAVAILABLE)
        if (!NONCE.matches(nonce)) return OwnEventAppendResult(OwnEventState.DENIED)
        val digest = sha256(nonce)
        if (digest in seenNonces) return OwnEventAppendResult(OwnEventState.DUPLICATE)
        val timestamp = clockElapsedMs()
        if (timestamp < 0 || timestamp <= lastElapsed ||
            nextId <= 0 || nextId == Long.MAX_VALUE
        ) return OwnEventAppendResult(OwnEventState.UNAVAILABLE)
        if (!prune(timestamp)) return OwnEventAppendResult(OwnEventState.UNAVAILABLE)
        if (seenNonces.size == MAX_NONCES) seenNonces.removeFirst()
        seenNonces.addLast(digest)
        if (records.size >= MAX_EVENTS) {
            records.removeFirst()
            droppedOverflow++
        }
        val value = OwnDiagnosticEvent(nextId, timestamp, origin, sensitivity, kind)
        records.addLast(Entry(value, digest))
        nextId++
        lastElapsed = timestamp
        if (!commit()) return OwnEventAppendResult(OwnEventState.UNAVAILABLE)
        return OwnEventAppendResult(OwnEventState.APPENDED, value)
    }

    @Synchronized
    fun openFakeSubscriber(caller: String, approved: Boolean): String? {
        if (stopped || faulted || !approved || caller !in FAKE_OWNER_NAMES) return null
        val token = randomToken()
        subscriberToken = token
        issuedThrough = ackedThrough
        lastCursor = null
        afterCursor = ackedThrough
        return token
    }

    @Synchronized
    fun page(token: String, cursor: String? = null, limit: Int = MAX_PAGE): OwnEventPage {
        fun reply(state: OwnEventPageState, eventList: List<OwnDiagnosticEvent> = emptyList(),
                  cursorResult: String? = null) =
            OwnEventPage(state, eventList, cursorResult, droppedOverflow, droppedExpired)
        if (stopped) return reply(OwnEventPageState.STOPPED)
        if (faulted || subscriberToken == null || token != subscriberToken) {
            return reply(OwnEventPageState.DENIED)
        }
        val after = if (cursor == null) ackedThrough else {
            if (cursor != lastCursor) return reply(OwnEventPageState.DENIED)
            afterCursor
        }
        if (!prune(clockElapsedMs())) return reply(OwnEventPageState.DENIED)
        if (cursor != null && records.isNotEmpty() &&
            after < records.first().value.id - 1
        ) return reply(OwnEventPageState.GAP)
        val selected = records.asSequence().map { it.value }
            .filter { it.id > after }.take(limit.coerceIn(1, MAX_PAGE)).toList()
        if (selected.isEmpty()) return reply(OwnEventPageState.EMPTY)
        val next = randomToken()
        lastCursor = next
        afterCursor = selected.last().id
        issuedThrough = maxOf(issuedThrough, selected.last().id)
        return reply(
            if (recoveredUnacked) OwnEventPageState.UNCERTAIN
            else OwnEventPageState.AVAILABLE,
            selected,
            next,
        )
    }

    @Synchronized
    fun acknowledge(token: String, throughId: Long): OwnEventAckState {
        if (stopped) return OwnEventAckState.STOPPED
        if (faulted || subscriberToken == null || token != subscriberToken ||
            throughId <= 0
        ) return OwnEventAckState.DENIED
        if (throughId <= ackedThrough) return OwnEventAckState.ALREADY_ACKED
        if (throughId > issuedThrough ||
            records.none { it.value.id == throughId }
        ) return OwnEventAckState.DENIED
        while (records.isNotEmpty() && records.first().value.id <= throughId) {
            records.removeFirst()
        }
        ackedThrough = throughId
        if (records.isEmpty()) recoveredUnacked = false
        if (!commit()) return OwnEventAckState.DENIED
        return OwnEventAckState.ACKNOWLEDGED
    }

    @Synchronized
    fun pendingCount(): Int {
        if (stopped || faulted) return 0
        if (!prune(clockElapsedMs())) return 0
        return records.size
    }

    @Synchronized
    fun droppedCounters(): Pair<Long, Long> {
        if (!stopped && !faulted) prune(clockElapsedMs())
        return droppedOverflow to droppedExpired
    }

    /**
     * Simulate a killed process in an isolated JVM test: release the OS
     * owner lock but deliberately leave only committed pending journal
     * records for the next process. No ack or completed delivery is invented.
     */
    @Synchronized
    fun simulateProcessDeath() {
        if (stopped) return
        stopped = true
        release()
    }

    /** Explicit service Stop forgets all diagnostics and cursor grants. */
    @Synchronized
    fun stop() {
        if (stopped) return
        stopped = true
        records.clear()
        seenNonces.clear()
        subscriberToken = null
        lastCursor = null
        try {
            Files.deleteIfExists(journal)
            purgeStaleStaging()
        } catch (_: Exception) { /* deny without exposing path */ }
        release()
    }

    override fun close() = stop()

    private fun release() {
        try { lock.release() } catch (_: Exception) { /* fail closed */ }
        try { channel.close() } catch (_: Exception) { /* fail closed */ }
    }

    private fun prune(now: Long): Boolean {
        if (now < 0 || (lastElapsed >= 0 && now < lastElapsed)) {
            faulted = true
            records.clear()
            return false
        }
        var expired = false
        while (records.isNotEmpty() &&
            now - records.first().value.elapsedMs > RETENTION_MS
        ) {
            records.removeFirst()
            droppedExpired++
            expired = true
        }
        return !expired || commit()
    }

    /** Record only fixed values; no original nonce or arbitrary text. */
    private fun commit(): Boolean {
        if (stopped || faulted) return false
        var staging: Path? = null
        return try {
            val output = buildString {
                append("N5C1|").append(nextId).append('|').append(ackedThrough)
                    .append('|').append(droppedOverflow).append('|')
                    .append(droppedExpired).append('|').append(lastElapsed).append('\n')
                for (nonce in seenNonces) append("S|").append(nonce).append('\n')
                for (entry in records) {
                    val e = entry.value
                    append("E|").append(e.id).append('|').append(e.elapsedMs)
                        .append('|').append(e.origin.name)
                        .append('|').append(e.sensitivity.name)
                        .append('|').append(e.kind.name)
                        .append('|').append(entry.nonceHash).append('\n')
                }
            }
            val bytes = output.toByteArray(Charsets.US_ASCII)
            if (bytes.size > MAX_JOURNAL_BYTES ||
                Files.isSymbolicLink(journal)
            ) throw IllegalStateException("EVENT_JOURNAL_INVALID")
            staging = Files.createTempFile(dir, ".events-", ".tmp", FILE_MODE)
            FileChannel.open(
                staging, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS,
            ).use { outputChannel ->
                val buffer = ByteBuffer.wrap(bytes)
                while (buffer.hasRemaining()) outputChannel.write(buffer)
                outputChannel.force(true)
            }
            Files.move(
                staging, journal,
                StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
            staging = null
            Files.setPosixFilePermissions(journal, FILE_PERMISSIONS)
            true
        } catch (_: Exception) {
            faulted = true
            records.clear()
            false
        } finally {
            if (staging != null) try {
                Files.deleteIfExists(staging)
            } catch (_: Exception) { /* no response disclosure */ }
        }
    }

    private fun loadJournal() {
        if (!Files.exists(journal, LinkOption.NOFOLLOW_LINKS)) return
        if (!Files.isRegularFile(journal, LinkOption.NOFOLLOW_LINKS) ||
            Files.size(journal) > MAX_JOURNAL_BYTES
        ) throw IllegalStateException("NATIVE_EVENTS_CORRUPT")
        val lines = Files.newInputStream(journal, LinkOption.NOFOLLOW_LINKS).use {
            it.reader(Charsets.US_ASCII).readLines()
        }
        val header = lines.firstOrNull()?.split('|') ?: throw IllegalStateException()
        if (header.size != 6 || header[0] != "N5C1") throw IllegalStateException()
        nextId = header[1].toLong()
        ackedThrough = header[2].toLong()
        droppedOverflow = header[3].toLong()
        droppedExpired = header[4].toLong()
        lastElapsed = header[5].toLong()
        if (nextId <= 0 || ackedThrough !in 0 until nextId ||
            droppedOverflow < 0 || droppedExpired < 0 || lastElapsed < -1L
        ) throw IllegalStateException()
        var priorId = 0L
        var priorTimestamp = -1L
        for (line in lines.drop(1)) {
            val parts = line.split('|')
            when {
                parts.size == 2 && parts[0] == "S" && HASH.matches(parts[1]) -> {
                    seenNonces.addLast(parts[1])
                    if (seenNonces.size > MAX_NONCES) throw IllegalStateException()
                }
                parts.size == 7 && parts[0] == "E" && HASH.matches(parts[6]) -> {
                    val id = parts[1].toLong()
                    val timestamp = parts[2].toLong()
                    if (id <= priorId || id <= ackedThrough || id >= nextId ||
                        timestamp <= priorTimestamp || timestamp < 0
                    ) throw IllegalStateException()
                    val event = OwnDiagnosticEvent(
                        id, timestamp,
                        OwnEventOrigin.valueOf(parts[3]),
                        OwnEventSensitivity.valueOf(parts[4]),
                        OwnEventKind.valueOf(parts[5]),
                    )
                    records.addLast(Entry(event, parts[6]))
                    priorId = id
                    priorTimestamp = timestamp
                    if (records.size > MAX_EVENTS) throw IllegalStateException()
                }
                else -> throw IllegalStateException()
            }
        }
        if (records.isNotEmpty() && lastElapsed < records.last().value.elapsedMs) {
            throw IllegalStateException()
        }
    }

    private fun purgeStaleStaging() {
        Files.newDirectoryStream(dir, ".events-*.tmp").use { entries ->
            for (file in entries) {
                if (Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) {
                    Files.deleteIfExists(file)
                } else throw IllegalStateException("NATIVE_EVENTS_BAD_STAGING")
            }
        }
    }

    companion object {
        private const val MAX_EVENTS = 64
        private const val MAX_PAGE = 8
        private const val MAX_NONCES = 128
        private const val MAX_JOURNAL_BYTES = 32 * 1024
        private const val RETENTION_MS = 120_000L
        private val NONCE = Regex("[A-Za-z0-9_-]{1,64}")
        private val HASH = Regex("[a-f0-9]{64}")
        private val FAKE_OWNER_NAMES = setOf("owner", "same-app", "this-app-owner")
        private val DIR_PERMISSIONS = PosixFilePermissions.fromString("rwx------")
        private val FILE_PERMISSIONS = PosixFilePermissions.fromString("rw-------")
        private val DIR_MODE = PosixFilePermissions.asFileAttribute(DIR_PERMISSIONS)
        private val FILE_MODE = PosixFilePermissions.asFileAttribute(FILE_PERMISSIONS)
        private val RANDOM = SecureRandom()

        private fun sha256(value: String): String = MessageDigest
            .getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

        private fun randomToken(): String {
            val bytes = ByteArray(24)
            RANDOM.nextBytes(bytes)
            return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        }
    }
}

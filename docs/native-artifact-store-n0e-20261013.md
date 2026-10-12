# N0.e — bounded Native private artifact store

**Scope:** internal Kotlin/JVM artifact lifetime service, plus Android's
app-private noBackupFilesDir adapter. There is no new MCP Tool, media
capture, SAF transfer, exported ContentProvider, external file access,
runtime permission, Root capability or public network listener.

## Security and lifetime contract

A future explicitly approved Android capture/SAF owner may open exactly one
NativeArtifactStore for its own lifetime and must close it when the owner
stops. The Android adapter fixes the root to Context.noBackupFilesDir; no
untrusted MCP argument can choose a filesystem path. The store creates
a dedicated native-mcp-artifacts child with POSIX owner-only directory
and file permissions. Symlink roots and symlink lock files are denied;
artifact reads do not follow symlinks. A guessed handle, forged URI,
traversal path or untrusted other-app path cannot resolve to an artifact.
The store never emits or logs raw content.

The default per-artifact budget is 8 MiB, per-owner aggregate 32 MiB,
16 live entries, and five-minute TTL (all configurable within hard
limits; maximum TTL 15 minutes, artifact cap 16 MiB, aggregate cap 64 MiB).
A cryptographically random 192-bit handle is encoded as 32 URL-safe
characters. Internally held receipts contain MIME, byte length, SHA-256,
created/expires times and opaque handle; raw bytes are never included
in a receipt or current public MCP output. Caller-supplied MIME is
validated as a bounded media type.

Writing uses a private temporary file, flushes file content, checks
the staged byte count and SHA-256, reserves a new destination with
exclusive CREATE_NEW, then uses an atomic rename before adding the
receipt to its in-memory index. Collisions, short writes, disk errors
and faults before commit never publish a partial handle. Read backs
verify private regular-file identity, exact byte count, expiry and
digest. Only the owning store may read, remove or purge entries.
Failures are fixed error codes without exception causes or device
paths.

A process-local JVM store additionally holds an exclusive OS file
lock. A second store for the same directory fails closed. On ordinary
owner Stop, close removes all managed content and releases the lock.
Following an unexpected process death, the OS releases its file lock;
the next legitimate owner **purges all untrusted old content before
serving any new handle**. No handle survives a restart. A crash while
the process is never restarted may leave app-private orphan bytes
until its next startup or app data deletion; no hidden background
cleanup, persistent external storage or crash-resilient encrypted
archive is claimed.

## Implementation status and test boundaries

The storage service and its Android noBackupFilesDir adapter are
implemented. The adapter is **inert** until a later gated media or
SAF work package constructs an owner; there are no captures yet.
This N0.e PR must not be counted as real Android screenshot,
recording, privileged file read or user-approved SAF access.

T-N0E-01..06 test real temporary private files, opaque handle and
digest, strict input denials, symlink and path traversal protection,
oversize/disk/short-write faults, atomic commit failure, collision
and concurrent-owner isolation, expiry, close, crash-orphan cleanup,
privacy and public status stability. The RED phase used a
deliberately incomplete store scaffold: all seven targeted tests
(six named plus one concurrent writer case) failed meaningful
behavior assertions. The actual Kotlin store, Python static
boundary guards, SDK36 compiled debug APK/Lint/permission allowlist
and complete local Host/Native quality checks provide separate
evidence. QEMU API30/33/34/36 end-to-end smoke is regression
protection for N2/N3 public behavior, not evidence of an Android
runtime artifact lifecycle because no sensitive Tool is enabled.

No physical Android device is touched, no Google license is
accepted and no paid GitHub Actions are required. Independent
security review remains a prerequisite to enabling public capture,
SAF exchange, or cross-process mutation authority.

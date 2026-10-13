# N5.c — bounded durable Native diagnostic event IDs and delivery uncertainty

**Scope:** Internal and synthetic/test-only diagnostic event ledger, not a live
MCP subscription, Android event listener, global Logcat reader or external
endpoint. The Android app continues to expose only device_status.
AndroidEventStoreBoundary always returns DENIED; no subscriber is
registered in the deployed APK.

## Private event data, identity and persistence

NativeDiagnosticEventStore accepts only fixed own-app event-code enums,
an allowed origin, coarse/redacted-private classification, and a monotonic
local elapsed timestamp. It does not store exception text, stack traces,
account data, Android serial/UID/PID, private paths, external package data
or original request nonce strings. The original nonce is SHA-256 hashed in
a bounded local replay ledger; no raw nonce or private subscriber token
appears in an event's public-style JSON.

A fixed private native-mcp-events directory is created only beneath
the caller-supplied app-private root (the intended Android root is the
application's Context.noBackupFilesDir). It refuses symbolic links,
uses private POSIX directory/file permissions and an exclusive owner
file lock. The fixed ASCII journal contains a format version, next
monotonic event ID, ACK high-water mark, explicit dropped-event
counters, last monotonic elapsed time, up to 128 replay digests and
up to 64 fixed enum-coded events. An atomic staging write with
FileChannel.force(true) and ATOMIC_MOVE replaces the committed
journal. A corrupted, symlinked or oversized journal fails closed,
with no guessed/truncated success. Stale staging files are deleted
when a new exclusive owner safely recovers.

The journal is bounded at 32 KiB. At most 64 pending events are kept,
and client pages contain at most eight. Capacity overflow drops the
oldest entries and increments dropped_overflow. Events older than
120 seconds are removed with an explicit dropped_expired counter;
a backwards/reset monotonic clock does not invent continuity or
fake delivery. A process restart keeps monotonically increasing IDs
from the committed journal but does not preserve a subscriber token.

## Cursor, ACK, crash and Stop behavior

A single synthetic subscriber is granted a random, process-scoped token
only to local unit-test fixtures with the expected fake own-app caller
and approval. This is **not real caller authentication** and is never
connected to MCP, HTTP or an Android external Intent. Each page
creates an opaque cursor bound to that in-memory subscriber; forged,
foreign, obsolete or cross-process cursors are denied. An ACK only
advances the high-water mark through a previously served event.
Duplicate or late ACKs cannot skip unserved events, insert a second
copy of a nonce or silently advance a caller cursor.

A synthetic process-death fixture releases the owner lock but leaves
only committed pending events in the private journal. A new process
gets a new epoch and subscriber token; those events can be inspected
again, but the page is explicitly UNCERTAIN until newly served
entries are acknowledged. It never infers successful delivery from
a previous MCP session or a crashed process. Explicit Stop purges
private journal records and staging, clears subscriber/replay state
and closes the file lock/channel, with no background listener,
thread, periodic sampler, automatic boot receiver or resurrection.

## Test-first evidence and activation limit

Six T-N5C-01..06 Kotlin/JUnit cases were written first and all six
failed meaningfully on an intentionally permissive scaffold. After
implementation, all six passed. Four extra JVM tests validate a
corrupt/symlinked journal's refusal, restart recovery and stale
staging deletion, concurrent eight-way ordered append with bounded
pages, and rejection of a backwards monotonic clock.
Six Python source/Manifest checks assert ID, cursor, exact owner lock,
atomic private write, bounded retention, absence of extra Android
permissions and an unmodified one-Tool Native MCP public catalog.

Local release requires full macOS JDK17 Host/Native quality and
security checks, Kotlin/JVM, real Python/Kotlin MCP transport, SDK36
signed APK, Android Lint and strict dependency integrity; then the
preverified disposable QEMU API30/33/34/36 matrix for existing
Activity/FGS, notification Stop and permission behavior. That emulator
matrix demonstrates backward compatibility, **not** live diagnostic
subscriptions or delivery guarantees. Real protected event delivery
requires independently reviewed retention/purpose policy and N6
authenticated caller/lease fencing before a new Tool can be enabled.
No physical Android, user logs or other-app data are touched here.

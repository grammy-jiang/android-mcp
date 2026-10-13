# N5.a — bounded app-owned crash and ANR diagnostic fixtures

**Scope:** Internal, synthetic-only own-app crash/ANR/foreground-service
failure reports. Production AndroidOwnCrashBoundary always returns DENIED.
No public diagnostic Tool, exception-handler installation, unrestricted
Logcat, cross-process tombstone collection, external file import or raw stack
trace capture is enabled in the current Native MCP application.

## Private information boundary

NativeOwnCrashDiagnostics accepts only an explicitly injected synthetic
event carrying this APK's own fixed package identity, per-instance random
process epoch, one-use nonce, Android API30+, sanitized own-app version,
finite nonnegative process uptime and one typed event code:
OWN_EXCEPTION, OWN_ANR or OWN_FGS_FAILURE. Any forged different package,
stale process epoch, malformed version, nonce replay or oversized duration
fails closed. The incoming exception message, raw stack, caller credentials,
emails, address and absolute paths are deliberately ignored and are never
serialized. Kotlin diagnostic toString methods redact both input and private
artifact receipts. Public-style metadata has only a fixed schema/status,
read_only=true, synthetic_only=true and live_diagnostics_enabled=false.

Accepted synthetic fixture data has a fixed, bounded JSON schema with
version, coarse uptime and event code. No raw exception text, process ID,
package inventory, outside app log, Android user ID or system-specific
error message appears in a report. An accepted internal report goes into the
N0.e owner-locked app-private artifact store, with SHA-256 and opaque random
handle and at most 16 KiB per report, four active reports and 120-second TTL.
Report data never crosses an MCP Tool or HTTP route. Only a caller already
holding the internal NativeOwnCrashDiagnostics instance may read an opaque
private artifact handle; arbitrary paths and guessed handles are refused.

## Lifecycle and concurrency

The private artifact owner is initialized on reporter construction, before
its first record. This reclaims orphan files from a stopped/crashed previous
process while holding the N0.e OS ownership lock. Another live process
cannot steal the owner lock or see the first process's receipts. Expired
records are purged and return no bytes. A simulated exception during
atomic report commit yields INCOMPLETE, never a retroactive success; it
closes the owner and denies further reporting until a new process-scoped
instance is established. Instance close purges files, releases the owner
lock and clears replay state. Duplicate concurrent nonces create only one
accepted report; bounded capacity refuses the fifth distinct report.
There is no background collection, scheduler, server listener or
auto-resurrection.

This is not a real production crash hook: a process killed before the fake
record path completes might leave no report, or an incomplete internal
partial file that the next owner will purge. The implementation makes no
claim to recover kernel ANRs, other app crashes or private OS tombstones.

## Test and activation evidence

Six T-N5A-01..06 Kotlin tests were authored before implementation and all
six failed meaningfully on the initial permissive scaffold. After
implementing bounded private reports and reboot/restart cleanup, they pass.
Three additional Kotlin tests verify eight-way duplicate reporting,
sensitive/malformed version and capacity denial, and an attempted
concurrent second owner with restart cleanup. Six Python source/Manifest
checks enforce no global Logcat, no privileged Android process inspection,
privacy and default-off MCP exposure.

Local release requires macOS JDK17 Kotlin/JVM, host and Native Python
quality/privacy/security gates, signed SDK36 debug APK, Android Lint,
locked dependency integrity and unchanged four-permission Manifest.
Preflighted disposable QEMU API30/33/34/36 tests verify existing public
MCP status, Activity and foreground-service lifecycles, not live
system crash or ANR tracing. No physical Android, other app, user log
or account is accessed. Actual own-app production crash capture would
need a separately reviewed callback lifecycle, privacy/retention plan,
user purpose and N6 caller identity before activation.

# N4.d — bounded synthetic SAF document export to an app-private artifact

**Status:** internal synthetic-only implementation. No production SAF file
reader, no ContentResolver access, no document picker, and no new Native MCP
Tool or Android permission. An actual user document is never read in this
work package; the Android boundary returns DENIED unconditionally.

## Exact selected-document and provider scope

The N4.c in-memory grant ledger has been strengthened to bind each fake
READ grant handle to the SHA-256 of exactly the original user-selected URI.
A different document at the same provider authority is therefore not
interchangeable with the approved URI. Its fake scope is always checked
before the provider callback and **again after reading, before publishing**
any private bytes. An additional check after private-file creation removes
the new artifact if the fake grant is revoked before completion.

NativeSyntheticSafExporter accepts only an explicitly injected
SyntheticDocumentProvider for Kotlin tests. It requires a current
synthetic READ grant bound to the exact selected URI. A returned document
must match that URI, a fixed allowlisted provider authority and an
independently specified fake provider-process identity. Provider errors,
mismatched authority/process, revoked/expired grant, wrong or missing
access mode, and a forged path/URI all fail closed. The fake provider
stream can never be obtained from a public MCP request or Android
ContentResolver in the deployed app.

An accepted fake document must have a bounded lowercase MIME type and a
size of 1 byte to at most 1 MiB; a declared size, when present, must match
the actual bytes. Reads are handled by one daemon worker with a 1.5-second
caller deadline, 8 KiB chunks and a strictly bounded memory accumulator.
Raw fake document bytes are copied into a private buffer which is
explicitly cleared after processing, including error and cancellation
paths. Uninterruptible provider reads remain a *worker uncertainty*, not
a success: there is no automatic retry or delayed artifact publication.
Cancellation can interrupt/close the provider while the outer operation
is awaiting it. A concurrent loss of permission or cancellation cannot
produce a trusted artifact.

Successful fake output goes through the previously reviewed N0.e
NativeArtifactStore: atomic private file publication, random opaque handle,
MIME/size/SHA-256, 60-second expiry, and automatic purge on owner Stop.
Maximum live documents per owner is four. Replaying the same process-local
idempotency key with an identical fake grant and URI returns the same
artifact handle without reopening the provider. A changed URI or grant
cannot reuse a key; expired, stale or process-restarted grants cannot
restore the prior result. Only a hash of the selected URI is retained in
the idempotency ledger. Request, provider and response debug strings
redact sensitive URI data and private artifact handles. Fixed
public-style metadata never exposes file bytes, ContentProvider identity,
document paths, account data or user tokens.

## Android adapter and activation gate

AndroidSafExportBoundary always returns DENIED. The current Android APK
does not connect its N4.c picker-result probe to a live exporter and does
not call openInputStream, openFileDescriptor or any provider mutation API.
No user-selected source is read, uploaded, disclosed or exported to MCP.
N4.d's safely executable scope is the tested private artifact processing
and precise denial contract, **not real Android SAF document export**.

Later work requires genuine ACTION_OPEN_DOCUMENT user selection,
independently verified OS URI permission and provider identity,
ContentResolver stream lifecycle, N6 authenticated caller/lease fencing
and independent security review before enabling any public result or
access to user files. A synthetic fake picker proof is not genuine user
consent and a URI string alone is never sufficient authorization.

## Executed engineering tests and limitations

The six specified T-N4D-01..06 JVM behavioral tests were developed first.
All six failed meaningfully on the initial intentionally incomplete
exporter scaffold and passed after implementation. Three additional tests
revealed genuine authorization-race and cancellation classification bugs:
revocation during provider read was initially allowed to publish, and
cancellation of a blocked provider was mislabeled BROKEN_PROVIDER. Both
were corrected; all nine tests now pass. A further Kotlin regression
pins the N4.c exact selected-URI grant, and six SDK-free Python safety
checks enforce limits, byte clearing, no raw URI logging, dependency
lock correctness, Android DENIED boundary, Manifest and one-Tool catalog.

The new native-lifecycle -> native-protocol module dependency uses the
already approved kotlinx-serialization 1.9.0 artifacts. Its Gradle lockfile
was regenerated through the existing --write-locks workflow without
disabling dependency verification, reducing security requirements, or
altering Host modules. Full JDK17/SDK36 local quality/security checks,
signed Android debug APK and Lint are mandatory before PR merge.

Preverified disposable QEMU API30/33/34/36 acceptance covers unchanged
N2/N3 local status and foreground-service behavior; this is **not**
emulator evidence of actual SAF file export, because none is enabled.
No physical Android device, user document, account, external storage
or system permission was modified. Remaining real consent/provider
tests are explicitly deferred and must not be counted as operational.

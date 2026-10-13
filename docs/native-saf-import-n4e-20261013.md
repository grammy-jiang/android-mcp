# N4.e — synthetic-only, non-executing SAF document import plan

**Status:** safe internal Kotlin/JVM planning model with default-DENIED Android
adapter. The APK still exposes only device_status; it does not open a
system document picker, write any ContentProvider or import a real user file.

## Authorization, document scope and cryptographic integrity

NativeSyntheticSafImportPlanner accepts only an explicitly injected fake
N4.c WRITE grant and one trusted N0.e private artifact. The fake grant must
be active, unrevoked and bound to the exact user-selected destination URI.
The destination authority/process must match the reviewed fake provider
identity. An unrelated document, provider, Content URI, forged caller/user
approval, cancelled picker result, missing document or READ-only grant
cannot produce a plan. Arbitrary filesystem paths and external storage
directories are not accepted.

The planner obtains source bytes only from a private NativeArtifactStore,
whose read path checks the original file identity, size, expiry and SHA-256.
The supplied expected digest must match the actual bounded document bytes.
Maximum source size for a plan is 1 MiB. Tampering, symlink replacement,
missing handle, malformed digest, oversized content or stale N4.c grant
fails closed. Private bytes are copied only into bounded process memory and
wiped after digest checking. Nothing is written to the selected provider.

A process-local idempotency key yields one deterministic SHA-256 plan ID.
Repeated identical fake inputs yield the same PLAN_ONLY receipt, but
a changed document, grant or request key cannot silently overwrite a
document or reuse the plan. Neither the digest nor plan ID is an
execution capability. Metadata contains no raw bytes, URI, account,
provider name, artifact handle, private path or key. Every result states
executed=false, synthetic_only=true, atomic_write_guaranteed=false
and requires_fresh_user_consent=true.

Immediately before a mock dispatch marker, the planner rechecks the
current N4.c WRITE grant and refuses a revoked or expired fake grant;
a previously prepared plan does not confer enduring authority.
Fake cancellation before a mock dispatch marker is CANCELLED.
Cancellation after a mock dispatch marker is UNCERTAIN, not success,
rollback or evidence of atomic writes. No Android OutputStream or
ContentResolver write occurs in either case. Process restart makes
old fake N4.c URI grant handles invalid; no deferred work or boot
receiver automatically resumes an import.

## Production Android boundary and security gate

The private AndroidSafImportBoundary always returns DENIED and exposes
no ContentResolver, OutputStream, file path or user permission mutation.
It neither launches ACTION_CREATE_DOCUMENT nor persists URI permissions.
This adds no MCP Tool or exported Android ContentProvider. The existing
four Android Manifest permissions remain unchanged.

Real N4.e import remains authorization-dependent: genuine user-selected
writable URI, current OS WRITE grant and verified provider identity;
platform stream/cancellation/failure semantics; independent security
review; and N6 authenticated caller and durable lease fencing. Android
ContentProviders generally cannot guarantee atomic file replacement,
so a future implementation must not claim atomicity absent separately
verified provider-specific evidence.

## Test-first evidence and limitations

Six specified T-N4E-01..06 Kotlin tests were written first. All six
meaningfully failed on the intentionally incomplete scaffold, then
passed. Four supplemental Kotlin tests verify revocation between planning and
a mock dispatch, six-way simultaneous
duplicate requests, symlink/corrupted artifact rejection, and fake
process restart and revocation denial. Six SDK-free Python tests pin
exact WRITE/URI/hash/size guards, absence of provider write code,
default Android denial, privacy and unchanged Manifest/public status.

Full macOS JDK17/SDK36 Host/Native quality, locked Gradle dependencies,
Python/Kotlin MCP interoperability, signed APK, Android Lint and
security/coverage gates are required before merge. A preverified
disposable QEMU API30/33/34/36 matrix checks existing status and
foreground-service/permission lifecycle, NOT a genuine SAF picker,
user-chosen destination or real file write. No physical Android
device, personal document, system setting or account is touched.

N4.e's independently safe planning portion is complete when all
gates pass; real user-consented import remains explicitly deferred
and must not be reported as enabled in production.

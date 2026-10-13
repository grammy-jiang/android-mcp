# N4.c — scoped Storage Access Framework URI grant boundary

**Status:** internal, synthetic-only SAF grant/permission model, plus an
Android read-only Activity-result adapter. No public MCP file Tool is enabled,
no picker is launched, no provider document is opened or written, and no
broad-storage permission or external file-manager capability is added.

## Genuine SAF consent and scope

The real Android Storage Access Framework grants document URIs only when
the user selects a document using system UI. A content URI string, Intent
grant flag, model-approved boolean, or simulated picker callback is
**not** proof of such a grant. AndroidSafPickerProbe is an unregistered,
read-only adapter for a possible later Activity-result owner. It examines
the result data, checks the exact current OS URI permission for this app
PID/UID with checkUriPermission and separately reads current persisted
URI permissions. It never starts ACTION_OPEN_DOCUMENT itself, calls
takePersistableUriPermission, opens ContentResolver streams, enumerates
providers or modifies system grants. A later Activity must independently
prove it launched the picker and received its genuine Activity result.

The testable NativeSafGrantPolicy accepts only fake, process-scoped,
same-user, own-picker ACTION_OPEN_DOCUMENT results with bounded one-use
nonces. Content URI syntax must be strictly content://, with an exact
reviewed authority, a document path (or tree/document shape), no userinfo,
port, query, fragment, traversal, file path, control bytes or double
encoding. Malformed/foreign provider URIs, file://, /sdcard, bad
cancelled results, lost Android permissions or wrong user deny with
fixed statuses and no sensitive URI/provider details in output.

READ and WRITE are separate explicit scopes. Both a corresponding
returned grant flag and a fresh matching Android OS permission
observation must be true. A WRITE grant does not imply READ and a READ
grant does not imply WRITE. Persistable capability is reported only
when the returned flags include PERSISTABLE and the OS already reports
a matching persisted grant; this code does not persist it. A
one-time grant remains one-time even when the provider supports
persistence.

The synthetic-only policy creates an opaque random 192-bit in-memory
handle scoped to the current process epoch, requested access mode and
a maximum 60-second monotonic TTL. At most eight live handles and
256 fake nonce replay markers are permitted. A revoked, expired,
missing or foreign handle never resolves to a document. On process
restart, an epoch changes and no handle or earlier grant is restored.
Even a recognized fake handle returns SIMULATED_ONLY; the method
realDocumentIoAllowed() permanently returns false. This is not a
real Android ContentResolver capability or authorization credential.

## Execution evidence and deferred functionality

Six specified T-N4C-01..06 Kotlin tests were written before production
implementation. All six failed meaningfully on a permissive stub,
then passed following denial-first implementation. Supplemental
Kotlin tests cover concurrent duplicate fake picker results (one
handle), capacity limits, stale process epochs, redacted diagnostics,
wrong OS flags, cancellation and provider permissions. A new
double-encoded traversal negative test caught an initially accepted
URI; the validator was hardened and all nine Kotlin tests passed.

Five additional Python source/Manifest checks verify OS URI permission
checks, no broad file permissions, no ContentResolver open or persisted
grant mutation, no arbitrary /sdcard access and unchanged live
status-only MCP catalog. Full local macOS JDK17/SDK36 Kotlin/JVM,
Python/Kotlin MCP interoperability, Host security, signed APK,
Android Lint and exact four-permission allowlist are required before
merging. The separate API30/33/34/36 disposable-emulator matrix
checks the existing public MCP and foreground-service lifecycle.
It is **not** evidence that a real system document picker was launched
or a real SAF grant was obtained by the app: no Activity-result
consumer is wired into the deployed APK.

The future N4.d export and N4.e import work must independently validate
actual user-selected provider streams, private-artifact integrity,
cancellation and real lifecycle behavior, and remain disabled until
reviewed caller identity/N6 security approval. No physical Android
device, personal document, account or permission setting is touched
by this work package.

# H2.c — Host-private, owner-scoped artifact records

The Host-side artifact store persists bounded synthetic output, build
artifacts and later approved inspection inputs without embedding private
binary bytes or absolute filesystem paths in MCP responses. It provides
a service API (`PrivateArtifactStore`) for **trusted Host code**, not a
remote upload/download facility. Neither this package nor its tests
install APKs, run Gradle, sign binaries or touch a physical Android
device.

## Storage and access model

A Host operator selects an absolute, non-symlinked private root. Its
ancestors must not be symlinks; the root and `objects/` directory must
belong to the current user and have exactly `0700` permissions.
The local secret and SQLite index are private (no world/group read).
The record table persists opaque random `art_...` handles, an HMAC'd
owner identity, a content-object key, SHA-256, MIME, byte count, creation
and expiry. Artifacts are private `0600` files, atomically promoted
from temporary files with fsync. Repeated content can share one physical
object **within an owner**, but identical bytes from another owner
receive separate objects and handles.

Each write enforces a maximum artifact byte count, a global live-data
quota, a record-count quota and a finite TTL of at most seven days.
The defaults are 8 MiB per item, 32 MiB live data, 256 records and a
one-day TTL. SQLite immediate transactions serialize concurrent
writers; a failed write never creates an acknowledged record. On
restart, bounded recovery removes stray temp files, orphaned objects,
expired records and revoked records. Unrecognized files, symlinks or
suspicious private permissions **block** the service instead of being
followed. Object reads re-check the owner, TTL, no-follow inode
properties, exact size and full SHA-256 digest. Calls cannot choose
arbitrary paths, shell commands, destinations or Android identities.

Filename inputs are restricted to short ASCII basenames and are
**never stored**. MIME types are allowlisted. ZIP/APK/AAB artifacts
must have a valid ZIP container; PNG, JPEG, PDF, UTF-8 text and JSON
are independently checked. Applications should not treat MIME/ZIP
checks as APK trust verification, signing validation or proof that
nested contents are harmless. That belongs to H2.e.

## MCP Tool: explicit, metadata only

The default three Host MCP Tools remain unchanged. For a trusted
local deployment, the operator can *optionally* enable only the
metadata Tool with explicit root and owner:

```sh
uv run --project host --locked android-mcp-host serve \
  --artifact-metadata \
  --artifact-root /trusted/private/artifacts \
  --artifact-owner trusted-local-owner
```

`host_artifact_metadata(handle)` is a **read-only** owner-scoped
lookup. Its owner comes from the Host configuration, not an MCP
request field. It returns a versioned bounded JSON Schema
(`urn:android-mcp:host-private-artifact-metadata:v1`) containing
only an opaque handle, digest, MIME, byte count and expiry timestamps.
It does **not** return raw bytes, a filename, owner identity or
filesystem path. Unknown, expired, revoked and cross-owner handles
produce the same generic `NOT_FOUND` response to avoid an oracle.

The private `put`, `read`, `revoke`, `list_metadata` and
`cleanup` service APIs are not remotely registered as MCP write
Tools. Metadata availability is not access authorization to install,
open in another owner context or download. An opaque handle is also
not a signed or delegated capability. The MCP listener remains bound
to localhost; authenticated external access and higher-privilege
artifact consumption remain separately gated.

## Tests and limitations

T-H2C-01–06 and additional test suites exercise concurrent duplicate
puts, SQLite restart, TTL/owner checks, quota enforcement, MIME
mismatches, random-handle collision, filesystem traversal, malicious
symlinks, changed files, crash/orphan cleanup, synthetic localhost
FastMCP metadata responses, real process startup/reaping and CLI
operator options. Test payloads contain only synthetic fixtures.

The store is a *same-user private data boundary*, not protection
against malware already executing as the current local user or
untrusted processes with direct write permissions to the store.
It does not encrypt data at rest, validate signing or grant SDK
licenses. Do not use it for personal captures until the relevant
future privacy and authorization gates pass. Recovery of process
termination does not replace host filesystem backup or power-failure
durability testing.

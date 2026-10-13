# H2.d — Durable Host job state, idempotency and fail-closed recovery

The Host-owned `DurableJobStore` provides persistent **metadata-only**
prepared, queued, running, succeeded, failed, cancelled and uncertain
states for later safe local build/emulator/profiling work packages.

**Important:** No executor, Gradle task, emulator, ADB operation, APK
installation, device lease or authorization grant is enabled by H2.d.
A job record is not permission to do a job. In particular, a parameter
`authorized=True` is limited to trusted internal Host call sites; it
is **not** a replacement for future signed-grant/Native-lease checks.
The public MCP Tool does not expose any mutable transition.

## Persistence and owner identity

A Host operator configures a private, absolute, non-symlinked job store
directory with mode `0700`, owned by the current OS user. It contains
a private `0600` 32-byte HMAC key and `0600` SQLite database. Neither
the raw owner name, request ID, target identity nor worker identifier
is stored: those are HMAC-keyed identifiers. Only a validated,
opaque randomly generated `job_...` handle, SHA-256 plan/result
digest, bounded machine-state enum and timestamps are returned.

Each trusted `prepare(owner, request_id, plan_digest, identity, authorized)`
invocation is idempotent: identical owner, request ID, plan digest and
identity always return the original job ID, including after restart.
Reusing a request ID with a changed plan or identity is rejected
(`IDEMPOTENCY_CONFLICT`). SQL `BEGIN IMMEDIATE` transactions make
concurrent writes serializable. Max records defaults to 1,000
(absolute maximum 4,096). When full, further requests **fail closed**
rather than auto-deleting an idempotency tombstone.

## State transitions and crash semantics

- `prepared → queued → running` is permitted only from a trusted,
  owner/target-identity-matching Host call, with a valid worker ID.
- Only one worker can claim a queued job. The claim atomically records
  generation, attempt count and finite lease deadline.
- The exact worker, generation, owner, target identity and unexpired
  lease must match before completion is recorded as
  `succeeded` (digest) or `failed` (bounded failure enum).
- Cancelling a queued or prepared job produces `cancelled`. Cancelling
  an *already running* job produces `uncertain`, not a fabricated
  successful rollback; it cannot be claimed again.
- A lease expiring on restart, or before completion, marks the job
  `uncertain`. Neither `recover()` nor a read-only status request
  retries the action. A later **trusted** reconciliation with an explicit
  evidence digest can record `succeeded` or `failed`, without
  performing/retrying the original operation.
- All transactions write an append-only, monotonically ordered
  sequence of typed audit events without raw private data.

Recovery is deliberately conservative. There is no automatic purging
of job IDs: retaining idempotency tombstones avoids unintended replay
of a potentially destructive request. An operator who exhausts the
bounded ledger must provision/rotate it through a separate reviewed
procedure; no public delete or "try again" shortcut is available.

## Optional localhost MCP status

The default three original Host Tools remain unchanged. A local Host
operator may opt in to the metadata-only status Tool:

```sh
uv run --project host --locked android-mcp-host serve \
  --durable-job-status \
  --job-root /trusted/private/jobs \
  --job-owner trusted-host-owner
```

`host_job_status(job_id)` reads one record within the **fixed Host
owner scope**, not a model-specified owner. A missing, malformed or
cross-owner handle returns the same generic `NOT_FOUND` result.
Its packaged v1 schema `urn:android-mcp:host-durable-job-status:v1`
contains state, digest, timestamps, generation and attempts only.
It never returns filesystem paths, target/owner/worker names, request
contents, command argv, process credentials or raw results.
`execution_enabled` remains **false**.

The server stays bound to `127.0.0.1`; H2.d does not enable external
MCP access. No untrusted request can queue, claim, cancel, reconcile or
authorize a job.

## Verification and limitations

Six required cases T-H2D-01 through T-H2D-06 plus adverse tests cover
read/write/restart, idempotency, invalid transitions, wrong owner or
target identity, concurrent claim races, cancellation, uncertain
worker crash, explicit evidence reconciliation, private file/SQLite
integrity, original default Tool compatibility, versioned FastMCP
structured responses, actual subprocess-isolated localhost MCP
and a cross-process race using entirely synthetic Python fixtures.
No real Android system, device or Gradle task is modified.

SQLite transactional metadata is durable on a normally functioning
local filesystem but does not provide Byzantine tamper resistance,
independent authorization, a trusted remote worker attestation or
cryptographic proof that an Android device-side action occurred.
Those additional gates must be implemented before any physical
or irreversible operation.

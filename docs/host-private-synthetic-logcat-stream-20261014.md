# Host H5.b — Finite Sanitized Synthetic Logcat Stream

**Date:** 2026-10-14. **Package:** H5.b (29/45).
Controlling references: `docs/host-mcp-implementation-plan-20261013.md`,
`docs/host-mcp-serial-test-cases-20261013.md` (T-H5B-01–06).
H5.a merge prerequisite: PR #114 / `61512d568ef89673127363191c54675d37942722`.

## Truthful capability boundaries

This is a **synthetic, finite, one-shot Logcat fixture** with durable
cursor-based polling, **not continuous live Android Logcat streaming**.
No real `adb logcat` process, physical device, user application logs,
USB transport, remote network listener or privilege elevation is enabled.
The pre-existing `adb_develop` Logcat snapshot contract is unaffected.
Production CLI `--logcat-stream-plan` injects neither a fixture reader
nor independent collection approval; starting collection is denied.
No client-supplied file path, serial, executable, shell argv, PID, device
selection fallback or broad Logcat filter is accepted.

Only a trusted test harness may inject a `StreamApproval` plus a
synthetic frame reader, pinned to the same durable job owner, exact
MCP-owned disposable AVD handle, verified *running synthetic* lifecycle
job, purpose, finite TTL and no more than 120 seconds future expiry.
A shared non-blocking AVD fixture lock prevents parallel fake capture
on the same test emulator. The service checks target and grant before,
after and during durable completion. Unauthorized, stale or ambiguous
targets never call the fixture.

## Contract, bounds and privacy

FastMCP Tool: `host_logcat_stream(action, avd_name, avd_handle,
lifecycle_job_id, request_id?, job_id?, cursor?, tag?, max_events=128,
page_size=8, ttl_s=60)`.
Actions `plan`, `start`, `poll`, `stop`. Versioned JSON output:
`host-synthetic-logcat-stream.v1.schema.json`.

- Input frame at most **65,536 raw bytes**, deadline **3 seconds**, exactly
  matching synthetic frame identity and complete flag.
- At most **128 sanitized events** in a private session; each HTTP poll
  returns at most **16 events**; finite TTL **1–120 seconds**.
  Larger raw frames fail closed. Extra valid lines are explicitly counted
  as dropped and `truncated=true`.
- Only threadtime-shaped fixed `McpTest`, `System`,
  `ActivityManager` synthetic tags and known priorities are accepted.
  Unknown tags, malformed lines and unprintable controls are omitted or
  rejected. An unknown requested tag is denied **before** subprocess.
- Only strict synthetic `STATE=...`, `EVENT=...`,
  `UPTIME_SECONDS=n` and `BATTERY_PERCENT=n` messages survive; all other
  syntactically valid messages become `[REDACTED]`. Raw bearer tokens,
  session credentials, emails, device serials, hostnames, IP addresses
  and arbitrary application text are **never persisted or returned**.
  The sanitized message allowlist is not a general real-world Logcat
  privacy attestation.

The durable cursor store is a private SQLite DB within the Host's
operator-pinned durable-job root. It uses a restricted 0600 database
and private secret, HMAC-hashed owner/target/lifecycle/request identities,
and an HMAC-signed `cur_<position>_<signature>` cursor. The private
stream row stores only bounded sanitized event JSON, checksum, cursor
position, truncation metadata and finite expiry; it never records raw
fixture stdout or stderr. Storage is bounded to **32 sessions**,
**32 KiB sanitized JSON per session**. Private TTL is enforced on
access, with expired rows purged on later insert; an idle database is
not a scheduled real-time deletion service.

All cursor polls use SQLite `BEGIN IMMEDIATE` to atomically consume
one page: an already-used, forged, malformed or cross-session cursor
cannot return the same page twice. After the final page, unread payload
is cleared and further polls are denied. `stop` discards remaining
events. Independent exact owner, request, lifecycle and job identifiers
must accompany every `poll`/`stop`; a cursor alone is not authority.
The SQL store validates stored records again before MCP disclosure,
including after corruption or malicious database edits.

## Durable sequencing, restart, cancellation and limits

`start` prepares, queues, claims and completes an H2.d job with an exact
operation digest. One capture runs once, sanitizes completely in
memory, stores sanitized events and commits a source checksum. The
confirmed job digest matches the sanitized SQL receipt checksum.
Identical start replay **never reruns** collection; it only presents
the current unconsumed cursor. A changed plan, uncertain job or
unverified lifecycle fails closed. After service restart, confirmed
unexpired sanitized pages are still consumable by the original owner.

`stop` during a running fake capture sets the cancellation event and
marks the H2.d job uncertain. Cancellation, missing fixture, disk error,
job commit failure, fake emulator disconnect, expired approval or
timeout can never be reported as confirmed successful collection.
Partial persisted session rows are discarded on failure. Do not retry
an unknown capture blindly. If a worker crashes, H2.d lease recovery
requires explicit reconciliation, not implicit job replay.

The optional **trusted-test-only** Python fixture child helper uses
an explicitly pinned owned Python script, fixed argv and isolated
process group, drains a capped pipe and kills its entire process
group on cancellation, timeout, output flood or process exit. No
production CLI or MCP argument can inject this child. An arbitrary
Python callback itself is not sandboxed; for hard deadlines use the
bounded child helper. This is not evidence of a real Android streaming
worker or privileged device operation.

## Acceptance matrix and follow-up

T-H5B-01 tests exact finite cursor pagination and monotonic offsets;
T-H5B-02 validates identity scope, duplicate cursor, lease and restart;
T-H5B-03 rejects hostile selectors/fields and proves redaction before
private storage; T-H5B-04 proves backpressure, truncation and finite
disk memory; T-H5B-05 exercises cancelled/failed/deadline/disconnected
workers and private-row cleanup; T-H5B-06 verifies typed MCP schemas,
real localhost Streamable HTTP and production CLI denial.
Additional negative tests cover consent, signed token tampering,
symlinks, cross-owner access, process-group kill, SQLite corruption,
idempotency and no physical access. All tests run with fakes/disposable
local fixture state; they do not infer real Android behavior.

**Explicit limitations:** Not a continuously running Logcat process,
not a physical-device acceptance, not a general Logcat redaction
guarantee, not a ChatGPT automatic Tool-selection attestation, and
not an automatic scheduled retention daemon. Enabling real Logcat
collection requires a separate security/privacy policy, consent and
device-specific acceptance. The next serial package is **H5.c**
bounded synthetic Perfetto tracing, beginning on merged `main`.

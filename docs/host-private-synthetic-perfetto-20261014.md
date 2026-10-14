# Host H5.c — Private Bounded Sanitized Synthetic Perfetto Trace

**Date:** 2026-10-14. Roadmap item H5.c (30/45).
Acceptance authority: `docs/host-mcp-implementation-plan-20261013.md`
and `docs/host-mcp-serial-test-cases-20261013.md` (T-H5C-01–06).
Serial predecessor: merged H5.b PR #117 / `5ff1dd9`.

## Capability boundary and test architecture

This is a deterministic **synthetic trace fixture**, **not** a real
Perfetto `.pftrace` binary and not an implementation of Android
Perfetto, `traced` or `trace_processor`. It does not attach to
running Android processes, invoke `adb`, read physical tablets, issue
root commands or capture sensitive system events. The private trace
artifact uses a small, versioned `mcp-synthetic-perfetto-v1` JSON
format with numeric test events, not a transferable Perfetto protobuf.
Do not present this as a supported Android real-world trace or
production instrumentation performance evidence.

Production only exposes the `--perfetto-plan` CLI opt-in, dependent
on an operator-owned disposable AVD, verified synthetic lifecycle,
durable jobs and private artifact storage. Production injects neither
fixture callback nor independent approval. It responds to `capture`
with a typed consent or execution denial; no raw capture is enabled.

Only a trusted test harness can inject a `PerfettoApproval` plus a
separate fake trace callback. The grant must match **exact durable job
owner, AVD handle, currently verified synthetic running lifecycle,
profile and purpose**, with independent positive `debuggable` and
`trace_supported` flags, finite future expiration and a short private
TTL. Mere host SDK availability, a device serial, or an MCP argument
does not grant tracing privileges. A nonblocking per-AVD fixture lock
serializes synthetic capture. Active collection gets a cooperative
cancel signal, and an independent Host durable-job lease prevents
implicit retries after uncertain worker recovery.

The MCP Tool is `host_perfetto_trace`, with operations:
`plan`, `capture`, `cancel`; arguments `avd_name`,
`avd_handle`, `lifecycle_job_id`, `request_id?`, `job_id?`,
fixed `profile`, finite `duration_s`, `max_bytes` and `ttl_s`.
The fixed profiles are `sched-lite-v1` and `frames-lite-v1`.
**No user-provided trace configuration, shell, executable, PID,
configuration filename, arbitrary output path, trace destination,
host/device serial or event-list override is accepted.**
The versioned JSON Schema is
`wire_schemas/host-synthetic-perfetto.v1.schema.json`.

## Bounded time, bytes and privacy

The test-owned reader is passed a three-second deadline (a trusted
fake callback has a post-call deadline check; a malicious arbitrary
in-process callback is *not* independently sandboxed). The binary
fixture envelope is bounded to **131,072 bytes**; requested maximum
must be between 1 KiB and 128 KiB. Requested finite duration must be
1–10 seconds, and private TTL 1–300 seconds. These are contract
fields, not proof that a real Android Perfetto tracer ran for that
duration. The fake trace must match the exact version, AVD, lifecycle,
profile, duration, synthetic and completion flags.

The fixed synthetic input uses `MCP_SYNTHETIC_TRACE_V1\n` followed
by at most 256 bounded ASCII lines. Only monotonic numeric timestamps
within the requested duration and fixed numeric `cpu_slice`,
`sched_switch`, `counter`, `frame_present` or `frame_dropped`
events can survive (profile dependent); at most 128 sanitized samples
are written. Oversized, reordered, corrupted, undecodable, binary,
NUL or control-bearing frames are rejected. Unknown printable
lines such as tokens, hostnames, IP addresses, credentials or
arbitrary process names are discarded **before** storage and counted
as redacted; they can never be represented as real trace measurements.
The sanitized serialized artifact is limited to **32,768 bytes**.
The private receipt contains only fixed test provenance, exact
target/lifecycle, schema and fixture versions, profile, duration,
requested byte cap, SHA-256, bounded sanitized sample/redaction counts,
opaque artifact handles and finite retention.

Both artifacts are saved in the owner-scoped private Host artifact
store only after complete sanitization, independently time limited and
available only through trusted private APIs. Ordinary MCP JSON returns
**metadata and opaque handles, no raw trace, local path, original
fixture body, secrets or arbitrary log entries**. Every read/replay
verifies the stored trace structure and canonical JSON serialization,
profile, duration, SHA-256, private owner/TTL, receipt purpose, job
identity and manifest digest. Tampered, stale, missing or expired
receipts cannot be replayed as `ok`.

## Idempotence, errors and cancellation

H2.d durable jobs bind the exact one-shot trace request digest to
the exact owned lifecycle. Identical successful requests replay only
the already verified private receipt without invoking the runner.
Conflicting requests, unknown or stale lifecycle, incomplete or
uncertain jobs, unauthorized callers and unsupported/undebuggable
fake targets are denied. Crash recovery does not silently rerun the
trace; failed, expired or uncertain outcomes are never reported as
a successful trace.

A `cancel` must match the exact original request, owner, target,
profile, duration, maximum, TTL and durable job ID. It signals the
active cooperative fake fixture and marks the result uncertain.
Worker timeout, revocation, device disconnect, private disk failure,
receipt torn write, failed durable completion, or cancellation
between trace and receipt commit revokes any staged private artifacts.
No real Android process-group termination is claimed because
**there is deliberately no real Perfetto child process**.

## Acceptance and nonclaims

Acceptance tests include T-H5C-01 through T-H5C-06, plus:
strict positive and negative FastMCP schemas; CLI default denial;
real localhost Streamable HTTP positive fake/negative production
paths; Unicode/control/oversize and monotonic numeric constraints;
secret redaction before private writes; wrong owner/lifecycle/approval/
profile/version; concurrent cancellation; restart replay; corrupted
receipt/digest, forged negative timestamp, private retention, staged
artifact rollback, failed job persistence and traceback/secret masking.

Do not infer real Perfetto support, real Android performance profiling,
real hardware availability, production consent, external security
attestation, ChatGPT autonomous Tool selection or Perfetto binary
compatibility from these deterministic acceptance tests. Enabling
an actual Android tracer requires separately reviewed consent,
data-exfiltration safeguards and real-device integration evidence.

After independently verified H5.c integration, proceed serially
to **H5.d — bounded synthetic Simpleperf profiling**.

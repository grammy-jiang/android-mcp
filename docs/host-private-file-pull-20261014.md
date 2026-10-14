# Host H4.d — Scoped Private Synthetic App File Export

Date: 2026-10-14. Serial Host roadmap: H4.d (package 25/45).
Specification: `docs/host-mcp-implementation-plan-20261013.md`, cases
T-H4D-01 through T-H4D-06 in
`docs/host-mcp-serial-test-cases-20261013.md`.

## Capability and execution boundary

This is a **complete deterministic synthetic-file test implementation**,
not live Android file pulling. Production `android-mcp-host serve` only
exposes a plan-only capability after the operator supplies all
`--file-pull-plan`, `--file-pull-package-id`, private AVD/lifecycle,
job-store and artifact-root prerequisites. The package must be pinned
under `org.example.synthetic.*`. Production constructs no reader,
Android ADB device access, shell command, file-system export process
or execution approval. The MCP Tool cannot supply an output destination
or replace a backend. Real physical-device reads and writes remain
**disabled**.

Synthetic fixture execution requires an independent private
`FilePullApproval` bound to exact owner, MCP-owned disposable AVD
handle, verified active H3.c synthetic lifecycle job, package, one
remote source, expected file SHA-256, export purpose, expiry and artifact
TTL. The grant is verified both before and after reading and before
publishing the artifact. The Host's nonblocking fixture lock prevents
overlap with other in-flight fake operations.

## Source allowlist

The source is **one** ASCII leaf directly under:

`/sdcard/Android/data/{operator_pinned_package}/files/mcp-export/{filename}`

The only supported suffixes and corresponding expected MIME types are
`.json` (`application/json`), `.txt` (`text/plain`) and
`.bin` (`application/octet-stream`). The leaf must match a
bounded ASCII allowlist. Unicode normalization tricks, `..`, NUL,
control characters, double separators, absolute external roots,
backslashes, nested paths, unknown package IDs, `/data` credentials
and `/system` are rejected before a fake reader runs.

An untrusted synthetic file frame must attest that the source is
regular, not a symlink, not partial, and belongs to the same exact AVD,
lifecycle, package, path, MIME and expected digest. The validator checks
the raw transferred bytes' SHA-256 itself; a response claiming a
different digest or manipulating the source identity fails closed.
A *synthetic flag is not real symlink attestation*. No promise is made
that Android's live scoped-storage permission or symlink semantics
have been validated; those are deferred.

## Bounded private artifact and durable receipt

A pull is limited to 1–1,048,576 bytes, default 262,144. The
`PrivateArtifactStore` enforces owner-scoped private objects, MIME
validation, bounded quotas and short, finite TTL. The durable job is
keyed to one owner + lifecycle + exact source. Its plan binds the
request ID, source hash, expected SHA-256, MIME and byte cap. A repeated
identical request reopens and verifies the private receipt and content
without executing again. A conflicting request is denied. Expired,
revoked, corrupted or wrong-owner artifacts cannot replay as success.

The only public success output is a typed metadata receipt with
opaque artifact/receipt/job handles, SHA-256, byte length and
safe source basename. Raw bytes, remote path, subprocess stdout,
private host paths, user data and base64 are **never returned** in
ordinary MCP JSON. A failed second private write, job commit, grant
expiry or disconnected synthetic target revokes partially created
private handles. Interrupted/unknown outcomes are marked
`uncertain`, not blindly retried.

A `cancel` action verifies the exact previous durable job/plan
and owner before changing state. It marks a running job uncertain
and signals the injected fixture's cooperative stop event. A
bounded synthetic subprocess (when used by fixture tests) is killed
as a process group on timeout. A late cancelled result cannot
publish a trusted artifact. A restarted process can observe the
uncertain job, but cannot claim that an unknown real transfer stopped.

## Public Host MCP contract and evidence

Tool: `host_file_pull` with `action="plan"|"pull"|"cancel"`,
`avd_name`, `avd_handle`, `lifecycle_job_id`,
`remote_path`, `expected_sha256?`, `mime_type`,
`max_bytes`, `request_id?` and `job_id?` (required for cancel).
The private output schema is
`host/src/android_mcp_host/wire_schemas/host-synthetic-file-pull.v1.schema.json`.

The output explicitly declares `synthetic_fixture_only=true`,
`real_pull_enabled=false`, `physical_device_reads_enabled=false`,
`physical_device_writes_enabled=false`, `raw_content_returned=false`
and `privacy_class="sensitive_private"`. Sensitive access has
truthful non-read-only/destructive annotations.

Test suites:

- `test_adb_file_pull_policy.py`: six mandated T-H4D cases.
- `test_adb_file_pull_faults.py`: hostile paths, metadata,
  symlinks, size, wrong grant, state loss and fault isolation.
- `test_adb_file_pull_receipts.py`: integrity, expiration,
  duplicate/conflicting exports, corrupt receipts and rollback.
- `test_adb_file_pull_cancel.py`: real threads, cooperative
  cancellation, no artifact after cancellation and bounded
  subprocess group termination.
- `test_adb_file_pull_http.py`: production CLI denial, genuine
  localhost Streamable HTTP and in-process FastMCP contract checks.

These deterministic tests are **not** tests against a real Android
emulator or physical device, certified MCP conformance, independent
external review or ChatGPT live tool selection. Before enabling
actual `adb pull`, independently review exact Android transport
pinning, OS-scoped permissions, symlink-resistant remote source
attestation, root safety, user consent, content exfiltration policy,
filesystem and device-side cancellation, and real-device acceptance.
Do not use test-only synthetic attestation as a live security proof.

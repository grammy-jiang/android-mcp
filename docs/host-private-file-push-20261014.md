# Host H4.e — Private Synthetic Signed File Import

Date: 2026-10-14. Roadmap package H4.e (26/45). Requirements:
`docs/host-mcp-implementation-plan-20261013.md`,
`docs/host-mcp-serial-test-cases-20261013.md`, cases T-H4E-01–06.

## Supported capability and disabled paths

H4.e provides a **complete deterministic synthetic-only import contract**,
a private artifact and durability model, and a production planning Tool.
It does **not** implement `adb push`, a real Android file write,
privileged scoped-storage access, a physical-device transport, an
Accessibility bypass, or remotely controlled file mutation.

Production `android-mcp-host serve` exposes `host_file_push` only after
explicit `--file-push-plan` and `--file-push-package-id` options together
with private owned AVD, lifecycle, durable job and private-artifact
configuration. Production does not inject an import fixture writer,
HMAC key or approval. It is **plan-only**; `push` returns
`MUTATION_DISABLED` without touching a device.

## Exact private source and destination

The source must be a private `PrivateArtifactStore` object owned by the
operator-pinned artifact owner, with a validated opaque handle, MIME,
finite byte limit and independently checked SHA-256. The Host does not
take an arbitrary source filename from the Tool request and never logs
source bytes or arbitrary shell commands. Limits are 1–1,048,576 bytes;
default 262,144.

The destination is **one ASCII leaf** directly below:

`/sdcard/Android/data/{org.example.synthetic.APP}/files/mcp-import/{leaf}`

Only `.bin` with `application/octet-stream`, `.json` with
`application/json` and `.txt` with `text/plain` are allowed.
Traversal, `..`, NUL/control characters, Unicode lookalikes,
absolute destinations outside this root, nested paths, backslashes,
hostile flags, unknown packages and symlinks are rejected.

No real-device remote symlink, permissions or atomicity inspection
exists in this implementation. Those guarantees are **not claimed**.
The synthetic test writer may return a `PushFrame` with a bounded
identity, checksum, length, atomic/complete flags, no-overwrite and
no-symlink assertions, all checked by the service; the frame is
**test evidence only**, not real Android filesystem attestation.

## Synthetic HMAC and consent

A trusted test harness may inject a finite-expiry `PushApproval`,
a private 32-byte fixture HMAC key, and a fake writer. The HMAC
attests only to the exact test-case fields: owner, private AVD handle,
active lifecycle job, synthetic package, destination, opaque private
artifact handle, SHA-256 and MIME type. Signature comparison is
constant-time. It is **not** an Android APK signature, signing
certificate, trusted user approval or secure remote attestation.

The service independently rechecks the approval and exact positive
H3.c synthetic emulator lifecycle before and after the fake write,
and again before committing its receipt. Physical devices, unknown
AVD handles, missing approvals and inaccessible sources are denied
prior to any injected writer invocation. Shared nonblocking fixture
locks fence overlapping Host synthetic actions.

## Durable jobs, private receipts and cancellation

A fixed owner-scoped durable job slot binds one disposable lifecycle
and exact import destination. The plan digest also includes source
handle, checksum, MIME, request identifier and size limit. An
identical repeated request verifies the private receipt and source,
then returns the original simulated outcome without re-executing the
write. Conflicting requests are blocked, and uncertain operations
are never blindly retried.

On success, the Host stores only a JSON receipt in its owner-scoped
private artifact store with a finite TTL. The Tool returns only a
job ID, opaque receipt handle, receipt digest, source digest and
bounded byte count. No source bytes, base64, remote absolute path,
private Host path, HMAC key or subprocess output is exposed.

A `cancel` action validates the **same** owner, destination,
source, plan and job ID, then marks the job uncertain and signals
the active fixture's cooperative stop event. A timed-out synthetic
child process run through the existing bounded process helper is
terminated; no automated retry follows. Unknown write outcomes,
incomplete/overwriting/symlinked fixture frames, approval expiry,
device disconnect and failed report writes cannot be committed
as success. A partially produced receipt is revoked on failure.
A prior fake filesystem write may still have happened before
cancellation and must not be described as rolled back.

## MCP and acceptance evidence

The Tool has actions `plan`, `push`, `cancel`. Its typed
`host-synthetic-file-push.v1.schema.json` declares a
`synthetic_hmac_fixture_only` attestation origin and explicitly
`real_push_enabled=false`,
`physical_device_writes_enabled=false`,
`synthetic_fixture_only=true`, and
`raw_content_returned=false`.

The `readOnlyHint=false` and `destructiveHint=true` annotations
disclose the sensitivity and potential side effects of a future
authorized import. Production remains default-denied.

Acceptance tests include all six required T-H4E cases, malformed
and mismatched HMAC grants, expiring consent, wrong owner, private
artifact corruption, destination traversal and symlinks, frame
spoofing, no-overwrite, durable cancellation and replay, partial
private artifact failure, bounded fake subprocess kill-on-timeout,
real in-process FastMCP, and a genuine localhost Streamable HTTP
MCP production denial contract.

These synthetic tests are **not** real Android/USB acceptance,
native scoped storage validation, independent external security
review, a certified MCP conformance test, or ChatGPT Chat/Work
tool-selection acceptance. Enabling real import would require
independently reviewed, OS-verifiable destination confinement,
real user-grant binding, device-side no-overwrite atomicity,
remote cancellation, integrity attestation and physical-device
acceptance; none is enabled by H4.e.

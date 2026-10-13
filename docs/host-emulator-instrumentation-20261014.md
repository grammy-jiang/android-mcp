# Host H3.e — pinned synthetic instrumentation job receipts

## Capability boundary

The optional `host_emulator_instrumentation` Tool is **disabled by
default**. Its production CLI flag `--emulator-instrumentation-plan`
requires approved H3.b private AVD provenance, H3.c lifecycle status,
an H2.d durable-job owner matching the AVD owner, and an H2.c private
artifact store. All paths, SDK image hashes, owners and binary
configuration are fixed at Host startup, never supplied as tool input.

**Real instrumentation, ADB installation, physical-device writes and
real emulator mutation remain disabled.** A production Host CLI never
injects an execution runner, so `run` is blocked. The approved offline
synthetic fixture test harness can inject a finite `fixture_runner`
that receives a fixed argument vector and returns bounded structured
test counts. It is not an ADB command, arbitrary shell or real Android
test executor. All published outputs declare
`synthetic_fixture_only=true`, `real_instrumentation_enabled=false`
and `physical_device_writes_enabled=false`.

## Approval checks and exact target

Every request rechecks an HMAC-owned disposable AVD handle, current
source/system-image hashes and existing local license receipt. A
synthetic test run additionally requires H3.c's **live, in-process,
confirmed running** fake emulator session for that exact AVD, identified
by the existing lifecycle job ID. A foreign, stale, unidentified or
post-restart process is never adopted via an emulator-looking serial.
The verified synthetic lifecycle is checked before and after the
fixture invocation; a child crash/restart in between is uncertain,
never a passing test report.

The test APK must be a private artifact under the operator-fixed owner
with APK MIME, exact caller-declared SHA-256, a fresh integrity-checked
store read and bounded structural ZIP validation. This does **not**
attest APK signing or Android installability. The explicitly bounded
instrumentation component accepts only a fully qualified package and
runner class, with no arbitrary options or additional ADB arguments.

The injected synthetic executor sees only a fixed list of positional
parameters binding the exact AVD name, lifecycle job, artifact digest,
and test component. Its stdout is never returned verbatim. Only strict
JSON summary values (`passed`, `failed`, `total`, `synthetic=true`),
finite resource budgets and a positive exit status can establish a
synthetic success. Nonzero exit, reported failures, untrusted extra
fields, stderr, truncated output, malformed JSON or timeout are not
reported as successful tests. No untrusted logs or diagnostics enter
private reports or public MCP results.

## Durability, privacy and failure recovery

Synthetic tests use the existing owner-scoped H2.d single-claim ledger.
The plan digest binds source AVD handle and image, current lifecycle
job ID, private APK handle and SHA-256, and test component. A repeated
request cannot change any field or silently run another test. The
worker persists a bounded JSON test report in the private artifact
store; MCP receives an opaque report handle, digest, job ID and case
counts only. If report storage or journal finalization fails after a
synthetic operation, the state becomes uncertain and is not replayed.

Cancellation uses the original request ID, job ID and entire pinned
plan. It may not cancel an unrelated Host build, snapshot, lifecycle
or instrumentation job merely because they share one private owner.
Duplicate completed requests can recover a valid private report handle
without rerunning; missing/revoked reports are not recreated.

## Acceptance and limitations

T-H3E-01 through T-H3E-06 and additional negative and local HTTP
FastMCP tests exercise synthetic pass/fail counts, private APK integrity,
fixed component and target selection, physical-device denial,
malformed output, runner/storage failures, timeout, restart, duplicate
request, durable replay and cross-job cancellation. No real Android
package is installed, no actual instrumentation is run on a device,
and no existing Native emulator is started, stopped or modified.

Real emulator instrumentation remains future gated work and is not
implicitly enabled by completing this contract package. Full
acceptance requires macOS ARM64 and sextant Linux ARM64 quality/test
matrices for Python 3.11–3.14, both Git-hook stages, clean wheel/sdist,
and exact integration-tree and post-merge verification. Hosted Actions
that never execute do not count as passing tests.

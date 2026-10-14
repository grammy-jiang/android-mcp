# Host H5.a — Bounded Private Sanitized Synthetic Bugreport

Date: 2026-10-14. Roadmap package H5.a (28/45). Acceptance
source: `docs/host-mcp-implementation-plan-20261013.md`
and `docs/host-mcp-serial-test-cases-20261013.md`
(T-H5A-01 through T-H5A-06).

## Execution scope and truthful capability

H5.a implements a **synthetic, deterministic diagnostic fixture only**.
It does not read real Android logs, invoke ADB `bugreport` or
`bugreportz`, connect to physical devices, bypass Android permissions,
or collect any live user diagnostic records.

The production Host `--bugreport-plan` option is an explicit
operator opt-in that requires trusted private AVD ownership, emulator
lifecycle, durable jobs and private artifacts. The production instance
injects **no collector or capture approval** and responds to
`collect` with `CONSENT_REQUIRED` or `EXECUTION_DISABLED`.
Tool arguments do not include shell commands, remote paths, output
file paths, arbitrary serials or a means to inject a test runner.

Only a trusted test harness may inject an independent expiring
`BugreportApproval` plus fake collector. These are pinned to the
exact owned disposable AVD, currently verified synthetic emulator
lifecycle job, owner, purpose and short artifact TTL. The Host
verifies the running lifecycle and grant before and after collection
and before committing any private report receipt. A shared fixture
lock fences concurrent synthetic operations.

## Bounded input and ZIP rejection

The test callback receives a 3-second deadline and 1 MiB maximum
archive envelope. This deadline is enforced by the bounded test-child
runner when invoked; an arbitrary malicious Python callback is not
an independent sandbox. A result is accepted only with the exact
fixed synthetic `bugreportz` marker
`OK:/bugreports/bugreport-mcp-fixture.zip`, synthetic flag,
completion flag and matching target identity. The marker is never
used to open a filesystem path or sent back in MCP output.

The sanitizer processes only two fixed ZIP members in order:
`version.txt` containing `BUGREPORTV1`, and `bugreport.txt`.
No nested files, duplicate/case-conflicting entries, arbitrary
filenames, symlinks, encryption, unsupported compression, corrupted
CRC, invalid member sizes, invalid version marker, decompression
bomb, truncated ZIP, undecodable UTF-8, NUL, control characters
or excessive text may be admitted.

Members are bounded to 32 KiB each, expanded data to 64 KiB,
at most 128 lines, and no more than 256 bytes per line.
Uncompressed/stored or Deflate input is supported. The sanitizer
re-emits a small deterministic ZIP with fixed member names and no
host- or Android-supplied archive metadata.

## Redaction before storage

Only strict numeric synthetic `UPTIME_SECONDS`,
`BATTERY_PERCENT` (0–100) and fixed `STATE` values
are permitted into sanitized `bugreport.txt`. Every other
well-formed line is replaced by the literal `[REDACTED]`.
Unknown account, password, token, log-ID, serial, email, hostname,
IP and arbitrary diagnostic lines therefore **cannot survive this
synthetic allowlist**. Raw captured data is validated and sanitized
in memory **before** any private artifact write or normal Tool output.

The resulting ZIP is *not a full Android bugreport*; it is a
deterministic privacy-safe synthetic derivative. This method is
not evidence of universal privacy protection for arbitrary real
diagnostics. Real reports would need a separately reviewed redaction
policy and real-device acceptance, which H5.a does not implement.

## Durable job, retention, privacy and cancellation

The owner-scoped job store uses one slot per lifecycle and binds
the exact request ID, target and fixed sanitized bugreport purpose.
Identical repeated requests replay only the verified private ZIP
and JSON receipt, checking artifact SHA-256, private owner,
status and sanitized shape, without rerunning the collector.
Conflicting, expired, revoked, uncertain, incomplete or corrupted
jobs are never blindly retried.

The sanitized ZIP and private JSON job receipt have an independently
granted finite retention TTL of 1–300 seconds. The ordinary MCP
result contains only the opaque artifact/receipt/job handles,
SHA-256, sanitized byte length, number of redacted lines,
explicit retention and typed status. No raw bugreport,
password, account identifier, ZIP entry contents, unbounded logs,
remote marker or unrestricted Host path appears in normal results.

A `cancel` request must name the exact job, owner and original
request. Active fake collection gets a cooperative cancellation
signal, the job becomes uncertain, and any private partial outputs
are revoked. Timeout, disk full, disconnection, expired grant,
missing report marker, malformed ZIP or durable completion
failure cannot be reported as a confirmed successful report.

## MCP contract and acceptance

Public Tool `host_bugreport` accepts `action="plan"|"collect"|"cancel"`,
`avd_name`, `avd_handle`, `lifecycle_job_id`, `request_id?`,
and `job_id?` for cancel. JSON Schema:
`host-private-bugreport.v1.schema.json`.

Every response identifies
`synthetic_fixture_only=true`, `sanitized_only=true`,
`real_bugreport_enabled=false`,
`physical_device_reads_enabled=false`,
`physical_device_writes_enabled=false`,
`raw_content_returned=false` and
`privacy_class="sensitive_private"`.
Sensitive/destructive MCP annotations reflect future privacy
implications but do not enable execution.

Acceptance tests cover required T-H5A-01–06 plus hostile ZIP
metadata and encoding, sensitive input redaction before private
storage, wrong owner/marker/lifecycle, expiration, concurrent
cancellation, bounded fake subprocess group termination, private
receipt replay, torn artifact writes, source/disconnect races,
in-process MCP and true localhost Streamable HTTP denial.

This package **does not** claim real Android bugreport or physical
tablet tests, certified MCP conformance, normal ChatGPT tool
selection, independent external review or real-world privacy
attestation. Real collectors must be reviewed separately before
they can be enabled.

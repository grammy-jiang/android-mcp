# Host H4.c — Bounded Private Synthetic Screen Recording

Date: 2026-10-14. Roadmap: H4.c (package 24/45). Specification:
`docs/host-mcp-implementation-plan-20261013.md` and
`docs/host-mcp-serial-test-cases-20261013.md`, T-H4C-01 through T-H4C-06.

## Truthful capability and security boundary

This package implements a **test-injected, synthetic-only video recording
contract** and owner-scoped private artifact/job receipts. It does **not**
implement live Android `adb screenrecord`, UI capture, media projection,
physical-device writes, Accessibility bypass, or access to another AVD.
Production has no media backend or approval injection and can only plan
recording after explicit `--screenrecord-plan` opt-in plus owned AVD,
lifecycle, durable-job and private-artifact operator prerequisites.
A normal MCP Tool caller cannot select a local path, shell command,
recording binary, arbitrary display, privilege or target over this boundary.

Fake execution requires a separate trusted `RecordApproval` with owner,
exact owned private AVD handle, exact positively running H3.c synthetic
lifecycle job, purpose, expiration and TTL. The grant is verified **before,
during, and after** the fake observation. A nonblocking shared fixture lock
prevents overlap with other synthetic AVD operations. Actual physical
emulator USB serials are never accepted.

## Bounded media and privacy

Only display 0, literal codec `h264`, whole-second duration 1–30 and
`max_bytes` 64–1,048,576 are accepted. Defaults: 5 seconds and 262,144
bytes. The fixture returns an **MP4-shaped synthetic test envelope** with
ordered `ftyp`, `moov` and `mdat` boxes and a tiny bounded payload.
This validator checks box envelope size/ordering and major brand but
**does not certify that the bytes decode into playable video**. It
cannot be used as a real-world codec verifier or secure-screen detector.
A separate, independently reviewed real video backend is required
before any live capture claims.

The test fixture returns media only to the trusted Host service. The
owner-scoped `PrivateArtifactStore` stores it as `video/mp4` with a
bounded quota, SHA-256, permission-controlled private file and finite
TTL. The durable job reports only opaque video and JSON receipt handles,
hash, bounded metadata, exact target and truthful capability flags.
Neither raw video, base64, OS paths, subprocess outputs, authentication
tokens nor arbitrary output filenames enter normal Tool JSON/logs.

The H4.c component has no exception that enables recording a secure
or locked window based on a caller-supplied grant. A test-injected
`RecordedClip` can have secure/locked metadata; that is explicitly
rejected. No real Android `FLAG_SECURE` attestation is claimed.

## Durable state and safe cancellation

The Host durable store uses a fixed owner-scoped request slot per
lifecycle. The plan digest binds the exact request ID, target, duration,
display, codec and cap. Identical calls replay the privately verified
receipt without re-execution; conflicting requests or stale/unknown
jobs fail closed. Failure/timeout or transport loss is **uncertain**,
not automatically retried.

A `cancel` action accepts only the original exact request and durable
job ID. It marks the job cancelled/uncertain, sets the active fixture's
cooperative cancellation event, and forbids a later success receipt.
The fixture may use `bounded_run` for a synthetic subprocess so that
timeout terminates the *test-owned subprocess group*. The production
CLI cannot launch a recording subprocess.

If writing a private video, JSON receipt, or durable success record
fails, any partially created private handles are revoked. Replay
checks the private receipt, video signature and SHA-256; revoked or
expired records remain unavailable, without blind recovery.

## Public MCP interface and testing

`host_screenrecord(action: "plan"|"record"|"cancel", avd_name,
avd_handle, lifecycle_job_id, duration_s=5, display_id=0, codec="h264",
max_bytes=262144, request_id?, job_id?)`.

The JSON Schema `host-synthetic-screenrecord.v1.schema.json` includes
`real_recording_enabled=false`, `synthetic_fixture_only=true`,
`physical_device_writes_enabled=false`,
`raw_media_returned=false`, sensitive privacy classification and
bounded metadata-only fields. Sensitive annotations are non-read-only
and destructive, since a future actual recorder would observe private
screen content. Production execution remains disabled.

Tests include T-H4C-01 through T-H4C-06, malformed MP4, fake
media/target spoofing, protected/locked windows, invalid request flags,
owner/consent/TTL denial, duplicate/restarted replay, corruption,
cancellation race, synthetic subprocess timeout/process-group cleanup,
partial private artifact rollback, real in-process FastMCP and genuine
localhost Streamable HTTP denial and schema equality, CLI plan-only
composition, and unchanged previous Tool families.

These tests are **not** real Android emulator or tablet tests, a
certified MCP conformance suite or an ordinary Chat/Work tool-selection
assessment. Before any real recording is enabled, independently review
identity/transport pinning, user permission and foreground indicators,
media storage encryption/retention, secure windows and truthful
redaction/privacy policy, bounded process lifetime and on-device
acceptance; these remain deliberately excluded from H4.c's safe scope.

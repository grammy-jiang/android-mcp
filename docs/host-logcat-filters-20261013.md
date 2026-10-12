# H1.e — bounded, filtered and best-effort-redacted Host Logcat

**Status:** implementation candidate, subject to exact-SHA cross-platform
verification and GitHub PR merge. **Scope:** only Host Python/MCP; no Native
APK, physical tablet operations, authentication changes or shared contracts.

The default Host process still exposes exactly the three public legacy Tools,
and `adb_develop` `logcat_snapshot` v1 has no behavior or Schema change.
An operator can opt in to a fourth, fixed-format read-only diagnostic Tool:

```sh
uv run --project host --locked android-mcp-host serve --adb-logcat-filter
```

The extra Tool `adb_logcat_filter` requires an explicitly selected online,
authorized, unambiguous ADB serial. Its optional parameters are integer
`lines` (10–200; default 100), `tag` (32-character ASCII-safe identifier),
`severity` (V/D/I/W/E/F), `package` (strict Android Java package grammar)
and `timeout_s` (0.1–10 seconds; default 5). Unsupported filters, negative/
nonfinite timeouts, shell metacharacters and unknown options fail with typed
denial and **zero** ADB execution.

The fixed command is `adb -s SERIAL logcat -d -t N -v threadtime`,
with optional Logcat-native tag/severity filters. An exact package filter
first resolves one numeric PID using `adb -s SERIAL shell pidof PACKAGE`;
absence, ambiguity and invalid PIDs deny the request rather than falling
back to another app or collecting global logs. None of these commands
installs apps, changes settings, connects transports, modifies forwarding
rules, supplies arbitrary remote shell input, or writes device data.

Each process is bounded to 64 KiB combined output, an explicit deadline and
process-group termination/reaping. The accepted response has a maximum 200
structured Logcat records, each message <=512 printable ASCII characters,
and an aggregate sanitized message budget of 16,000 characters.
Unexpected or over-limit outputs, stderr, malformed records and truncated
results retain a typed `partial`, `timeout` or `error` state. Raw
untrusted stderr and discarded records are never returned or persisted.

**Privacy:** This Tool uses *best-effort*, not comprehensive, redaction of
common credential assignments, Bearer tokens, email addresses, IPv4 and MAC
addresses, long identifier-shaped strings, the selected device serial,
ANSI escape sequences and control characters. It is still a sensitive
diagnostic read: unknown free-text personal content can appear in a
successful result. Require an appropriate authorized diagnostic purpose;
do not record or publish captures casually. The Tool description warns
clients, and no disk log or raw capture is created by this provider.
No remote unauthenticated exposure is enabled; `serve` stays loopback-only.

The Host-only v1 JSON Schema
`urn:android-mcp:host-logcat-filters:v1` is packaged in the wheel.
Six required T-H1E-01–06 cases and supplemental adversarial tests cover
exact argv, target authorization, invalid filters, redaction, app PID lookup,
timeouts, overflows, real process cleanup, no-data/malformed responses,
real in-process FastMCP Tool metadata/Schema, and fake-executable localhost
HTTP. These synthetic tests do not establish real-device capture
suitability or production remote-client authorization.

# H0.b — opt-in fixed-path Host toolchain inventory

**Status:** implemented as a local read-only inventory adapter and an
opt-in FastMCP Tool, subject to the H0.b exact-SHA cross-platform gate.
**Ownership:** Host only. This does not change Android Native files or
the shared `contracts/**` wire protocols.

Start the extra Tool with
`android-mcp-host serve --toolchain-inventory`. The normal
`android-mcp-host serve` still exposes precisely the three original
public Tools (`device_status`, `adb_observe`, `adb_develop`). This
incremental opt-in keeps the H0.a frozen catalog valid while H0.c
designs supported capability profiles.

The fourth Tool, `host_toolchain_inventory`, accepts no parameters.
It returns a versioned, typed Host-only
`urn:android-mcp:host-toolchain-inventory:v1` structured response.
Records distinguish `available` (file/SDK presence) from
`runnable` (bounded version probe succeeded), with stable reasons
such as `NOT_INSTALLED`, `PERMISSION_DENIED`, `MALFORMED_VERSION`,
`TIMEOUT`, `OUTPUT_LIMIT`, `NONZERO_EXIT` and `EXEC_FAILED`.
`status: partial` never means the missing SDK or provider was
implicitly authorized.

The provider probes only allowlisted fixed Host installation paths:
ADB `version`, Fastboot `--version`, Java `-version`,
Gradle `--version`, and SDK platform-marker files. It never
trusts PATH order or accepts model-provided executable paths, flags,
Gradle tasks, SDK installation requests or license acceptance.
The bounded subprocess runner uses argument vectors, 64 KiB
stdout/stderr capture, short timeouts and process-group cleanup.
SDK platform directory scanning is capped at 128 entries and ignores
symlinked platform directories.

The Tool is loopback-only, disabled by default, and conservatively
advertises `readOnlyHint: false` because launching version probes
may populate Host tool caches even though it does not intentionally
write to an Android device. `destructiveHint: false`,
`idempotentHint: true`, and `openWorldHint: false` describe the
specific bounded operation.

**Limitations:** Version availability is not proof of an Android
license, valid SDK installation, connected device permissions or
authorized physical mutation. This slice does not perform H2.a's
complete SDK/NDK integrity preflight. Only authorized Host-side code
may provide explicit fixed paths for testing; MCP clients cannot.

**Verification:** six H0.b numbered tests plus negative/edge cases,
real in-process Tool metadata/Schema/response and fake executable
localhost HTTP calls. The clean wheel-install gate also checks that
the packaged Host-only output Schema is available. Actual exact-SHA
cross-platform results are recorded in the H0.b PR rather than
declared passed in advance.

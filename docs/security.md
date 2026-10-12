# Security and privilege boundaries

## Threat model

A network-exposed MCP endpoint can receive model-generated requests. Android devices may hold app credentials, photos, notifications, address details, payments or development secrets. ADB/Root and native Accessibility are highly privileged automation surfaces.

## Defaults of the integrated Host candidate

- Three public Host tools: `device_status`, `adb_observe`, `adb_develop`. The latter two require explicit device IDs and registered ADB devices.
- `serve` binds to `127.0.0.1` only and rejects other listen addresses.
- No root, arbitrary shell/ADB command, executed APK install, executed instrumentation, live device mutation, or Android credentials. Signed-grant and Host lease components are prototypes but **not enabled by production server composition**.
- The legacy boolean approval/lease hooks have been removed; a mutating operation can only reach an injected secure coordinator, which itself requires an independently trusted signed grant and unimplemented Native lease bridge.
- Logcat and package diagnostics may expose sensitive app data. Keep the server loopback-only, do not persist raw captures in audit records, and apply narrowly scoped capture limits.
- No remotely accessible service or tunnel is created by repository setup.
- No screenshots, UI dumps, secrets or serial numbers included in CI logs.

## Future boundaries

**Host MCP**: ADB/Fastboot adapter, explicit serial selection, typed permitted operations, privilege categories, bounded timeouts, redaction, audit of all mutations. Do not pass through arbitrary `adb shell` simply because the host can run it.

**Native MCP**: network listener as a non-root process; AccessibilityService restricted to its granted permissions; optional privileged broker with authenticated local IPC and separate capability/policy checks. Do not run the public MCP listener as root or expose a root broker over TCP.

**External access**: TLS, strong caller authentication, Origin and Host validation, auditable authorization by operation type, deny-by-default. Add remote transport only after end-to-end client capability and screenshot validation. A localhost-only server is not remotely reachable by ChatGPT Cloud.

**Approval policy**: read-only inspection is lowest impact; UI interactions may expose/alter account state; APK data clearing, app uninstall, reboot, bootloader commands, partition flashing and purchase/payment operations require stronger approval or are unavailable by default. No bypassing third-party security or integrity checks.

**Coordination**: concurrent Host/Native mutating operations require an exclusive device lease; no automatic escalation to force-stop or root on lease failure. Recovery operations must be explicitly scoped and auditable.

**Data retention**: device IDs and diagnostics can be sensitive. Never commit pairing tokens, USB keys, captures, account details, personal data, API tokens, or signing credentials. Default diagnostic errors should be concise and redact environment secrets.

## Acceptance gates before any public deployment

1. Authenticated HTTPS remote entry point; localhost-only listeners remain internal.
2. Separate tool permission tests on ChatGPT **ordinary Chat** and **Work** where applicable; don't infer one from the other.
3. Verify screenshots are actually consumed by the model, not merely encoded into an MCP response.
4. Timeout/lease/recovery tests for state-changing actions.
5. Explicit user approval on operations with lasting/destructive consequences.

Successful mock tests and local HTTP calls do not establish Native lease safety or an authenticated remote MCP. Production high-privilege operations remain disabled until device identity pairing, verified Native lease fencing, authorization and an independent security review are complete.

## Bounded ADB captures (Host candidate)

Host ADB version/discovery and fixed read-only probes use the same bounded,
process-group-managed subprocess runner as other Host operations. Each command
has a strict 64 KiB byte capture cap; flooded output must be rejected, never
silently parsed as complete. Every command uses an argv vector without a host
shell. Bounded size does not make device diagnostics non-sensitive.

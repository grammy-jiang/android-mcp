# Android MCP — Host H1 design and implementation handoff

**Status:** prepared off-device for integration. This is an incremental, reviewable patch to the existing `android-mcp` Monorepo. It does **not** claim deployment, GitHub CI, or actual tablet execution.

## 1. Why the Host runtime exists

`android-mcp` has **two independent MCP servers in one repository**:

- `host/`: Python + FastMCP on macOS/Linux, and official ADB/Fastboot binaries.
- `android/`: Kotlin Native MCP on the dedicated tablet, using Android APIs (later including a separately protected privilege broker).

The Host exists for device setup, debugging, APK/ROM lifecycle, diagnostics and recovery. The Native runtime is the preferred control plane for ongoing UI/commerce automation. Neither is a required runtime dependency of the other, and Binnacle stays separate.

## 2. H1 scope: safe, typed observation

Adds exactly **one** publicly registered MCP tool, `adb_observe(device_id, probes)`, beside the existing `device_status`.

No model-supplied command string, `adb shell` argument, property key, package name, executable path, `su` or `adb root` is accepted. The device serial is required and must match a **currently online, authorized** device returned by `AdbClient.inspect()`; this is not a guarantee that Android has completed booting. Invalid/unrecognized values are rejected before invoking ADB.

Each listed probe is internally represented as a **fixed argument vector** (`subprocess.run`, `shell=False`) and executed with an explicit timeout. The observation output is bounded before being sent through MCP; stdin is never supplied, no file is changed, and no ADB TCP debug listener is opened.

| Probe ID | Fixed command purpose | Returned keys |
| --- | --- | --- |
| `identity` | Selected build properties | manufacturer, model, android_release, api_level, build_type, lineage_version |
| `boot` | Boot completion + debug/verified boot indications | boot_completed, debuggable, verified_boot_state |
| `battery` | `dumpsys battery` | battery |
| `display` | `wm size` and `wm density` | size, density |
| `storage` | `df -k /data` | data_free |
| `selinux` | `getenforce` | enforcement |
| `shell_identity` | `id` under ADB shell identity | identity |
| `third_party_packages` | `pm list packages -3` | packages |

Commands are read-only in ordinary Android semantics, but `adb devices` may still start the **host** adb daemon. Results can include sensitive device metadata and package lists; client access needs authentication before remote exposure.

## 3. Contract

Output `contracts/adb-observation.v1.schema.json`:

```json
{
  "schema_version": 1,
  "runtime": "host",
  "device_id": "SERIAL",
  "status": "ok",
  "results": [
    {
      "probe": "selinux",
      "fields": {"enforcement": "Enforcing"},
      "truncated_fields": []
    }
  ],
  "errors": []
}
```

`status` is `ok`, `partial` or `error` and errors have stable `code`/`message`. Results from completed probes are retained if a later command fails. No output or error should silently look like successful data. `INVALID_DEVICE_ID`, `INVALID_PROBES`, `INVALID_PROBE`, `ADB_NOT_FOUND`, `DEVICE_NOT_FOUND`, `DEVICE_NOT_READY`, `PROBE_TIMEOUT`, `PROBE_EXEC_FAILED`, `PROBE_FAILED`, `OUTPUT_LIMIT` are typed error codes.

The data contract is **not** a promise that an App with accessibility or a rooted ROM can be controlled via Host M1. Those capabilities belong to later workstreams and actual hardware gates.

## 4. Host/Native coexistence

Normal mode: Native owns UI actions; Host may observe on ADB. `adb_observe` is not a mutation lease owner because it does not change device UI or app state. Later Host deploy/reboot/force-stop requires an explicit device, operation class, user approval policy, and a **paired Host/Native lease**. The lease must be fail-closed when Native is reachable. Break-glass Host recovery remains possible when Native is demonstrably unavailable and is independently audited.

Never infer Host/Native device pairing by comparing a USB serial to the Android installation ID. Pairing requires a documented authenticated handshake.

## 5. Testing and quality gates

`test_probes.py` covers explicit serial selection, unauthorized/offline/recovery, invalid probe names and lengths, no-device and no-ADB, timeout, subprocess errors, failed output, partial results, truncation, bounded output, fixed argv, no Shell invocation, and registry capability integrity.

`test_observation_contract.py` validates success/failure result schema through `jsonschema`. `test_server_observation.py` exercises the FastMCP adapter in-process; it needs the project-locked FastMCP installation and **has not been executed in the isolated environment**.

The pure Python component is runnable without ADB, a tablet, network, Android SDK or Root. The follow-up validation on Mac/Linux must run:

```bash
python3 scripts/dev.py doctor --json
python3 scripts/dev.py check
uv run --project host --locked --group dev pytest -q host/tests/test_server_observation.py
uv run --project host --locked --group dev pre-commit run --all-files
uv run --project host --locked --group dev pre-commit run --hook-stage pre-push --all-files
```

Then perform exact-SHA GitHub Actions on Ubuntu/macOS and isolated wheel install before merge. Add `src/android_mcp_host/probes.py` to the **95% critical coverage** modules in `quality-policy.json`.

### Known boundaries

`subprocess.run(capture_output=True)` reads full command output before `ProbeService` trims the MCP response. The fixed H1 command registry limits ordinary output in practice, but this does not prove a hard memory cap against malfunctioning ADB/device output. The H2 execution engine should implement byte-bounded streaming, cancellation and a guarded per-device queue before adding potentially long-running package/logcat/bugreport operations.

This patch has not proven real `adb shell` permission behavior on the tablet. ADB identity, SELinux and root availability must be measured on the connected LineageOS device rather than assumed.

## 6. Host H2 scope — development lifecycle engine

1. A **typed command policy** (`ADB shell` raw pass-through remains disabled by default): read-only diagnostics, APK install/update/uninstall, instrumentation test triggers, controlled logcat/Perfetto capture, Fastboot/recovery transition, and backup/restore where platform-supported.
2. Command authorization: one explicit target, capability scope, operation class, approval token for destructive changes, safe transport and optional audit correlation ID.
3. Completion semantics: operation ID, deadline, output byte limit, stdout/stderr redaction, cancellation, exit/signal classification, and idempotency when applicable.
4. Device coordination: normal UI control stays Native, app maintenance obtains a lease, privileged recovery has an explicit audited break-glass path.
5. Cross-platform adapters: `shutil.which` for binaries, `launchd` on macOS and systemd on Linux only as deployment adapters, no platform-specific code in domain handlers.
6. Test fixtures: offline, unauthorized, multi-device, USB disconnect during execution, hung adbd, invalid serial, malformed shell output, process tree cleanup and crash recovery. No real-device test in standard CI.
7. Live device gates: authorized USB-debug session, `id`, build version/ROM, app install on **test APK only**, instrumented test, bounded log capture, device restart/reconnect and rollback.

H2 mutating tools must remain unregistered until these gates have evidence.

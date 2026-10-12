# Android MCP — Host H2 typed engineering commands

**Status:** offline review implementation. It has not been deployed to the MacBook/Raspberry Pi or tested against the dedicated Android tablet. H1 integration and Q1 CI remain prerequisites. The actual FastMCP integration test is included but cannot run in this offline environment until the project-locked FastMCP environment is available.

## 1. Scope and operating boundary

H2 extends Host H1 with exactly one additional public MCP tool: `adb_develop(device_id, action, dry_run=False)`.

| Action type | Effect | Parameters | Default policy |
| --- | --- | --- | --- |
| `logcat_snapshot` | Read | `lines` (10–2000, default 200) | Executable against authorized online device |
| `package_details` | Read | `package` | Executable against authorized online device |
| `instrument_test` | Changes device/app state | `package`, `runner` | Plan only; execution disabled |
| `install_apk` | Changes installed packages | `apk_path`, `replace`, `allow_test` | Plan only; execution disabled |

No raw host shell, raw `adb shell`, `adb root`, root privileges, reboot, network ADB enablement, app data clearing or bootloader operations are exposed. H1 `adb_observe` remains separate and read-only. No shopping-specific behavior enters the ADB Host layer.

**Mutations are not enabled merely by passing `dry_run=False`.** The default server deliberately lacks three trusted, host-side prerequisites: an operator approval verifier bound to the exact requested action, a Host/Native device-lease coordinator, and a durable audit sink. User-provided MCP arguments cannot install these components or self-approve a mutation. Tests can inject safe fake gates to prove the execution branch is instrumentable; this is not a production policy implementation.

## 2. Command and device validation

The server first checks device serial syntax, then action shape and all arguments, then a fresh ADB device list. Only exactly selected, authorized, online devices proceed. It never silently chooses the first device or accepts input that becomes an arbitrary Android shell command. Java package and runner names are conservative ASCII identifiers because `adb shell` is **not equivalent to host shell=False**—remote shell interpretation still matters.

For APK installation, `allowed_apk_roots` is a trusted Host configuration, never an MCP input. Resolve the candidate and each allowed directory, reject path traversal outside the approved roots and file symlinks, require a regular `.apk` with a ZIP local-file signature and a bounded file size. This is a path safety gate, **not** an APK signature verification. Before enabling live install, add immutable artifact staging plus hash-verified approval to close remaining filesystem time-of-check/time-of-use risk.

Commands use argument vectors (`Popen(..., start_new_session=True)`), dedicated process group and bounded output capture. The runner reads stderr/stdout concurrently, kills the local process group on timeout/byte limit and returns a typed result. The local child terminating does **not** guarantee a test already started remotely is canceled: future durable-task/reconciliation logic must cover that.

## 3. Return contract

`contracts/adb-development-action.v1.schema.json` and `contracts/adb-development.v1.schema.json` define versioned inputs and results:

```json
{
  "schema_version": 1,
  "runtime": "host",
  "device_id": "DEVICE-ID",
  "operation": "logcat_snapshot",
  "status": "ok",
  "mutating": false,
  "dry_run": false,
  "command": ["adb", "-s", "DEVICE-ID", "logcat", "-d", "-t", "200", "-v", "threadtime"],
  "result": {"exit_code": 0, "stdout": "...", "truncated": false},
  "errors": []
}
```

`status` is `ok`, `planned`, `partial` or `error`. The raw stderr and runner exception text are deliberately not returned. `OUTPUT_LIMIT` and result-unconfirmed states must never report confirmed success. Instrumentation success additionally requires both `OK (...)` and `INSTRUMENTATION_CODE: -1` for the supported runner format; unusual runners are conservatively reported as unconfirmed. Redaction of personal data **inside** the requested Logcat stdout is not possible in general; account and app data must be handled with explicit permission and retention policy before remote exposure.

## 4. Concurrent Host/Native actions

The implementation has a per-device **in-process** non-blocking lock, sufficient only to avoid simultaneous actions through one Host instance. It is not distributed control ownership across the Android Native and Host MCP servers, and cannot survive host process restart. Host mutations remain disabled until the cross-runtime lease design and authenticated pairing protocol are implemented and tested. The Native UI service is not present in this release.

## 5. Tests and acceptance gates

- `test_command_plan.py`: strict allowlist, invalid inputs and package injection, APK paths, symlinks, flags.
- `test_command_runner.py`: real local subprocess, timeout, output exhaustion, separate stdout/stderr.
- `test_operations.py`: explicit-device checks, fail-closed authorization/lease/audit, typed exceptions, lock conflicts, result interpretation.
- `test_operation_contract.py`: response schema for success/plans/errors/partial results.
- `test_server_development.py`: actual FastMCP catalog and tool calls (requires the locked project dependencies; **pending**).

Before integration: apply H1 and H2 in order on top of the current `feature/quality-foundation` branch after verifying clean ownership and status. Run `python3 scripts/dev.py check`, both Git hook types, the complete macOS/Linux CI matrix, sdist/wheel clean-install smoke and an authenticated end-to-end MCP call. Any new production source module must be included in the fail-closed coverage inventory with the critical policy for device validation, command planning, execution and authorization.

## 6. Next slices (not implemented)

H3: trusted operator approval and one-time immutable APK artifact grants; persistent, cross-runtime device lease (including expiry, fencing and break-glass recovery); durable background jobs for instrumentation and large diagnostics; signed artifact metadata and local retention policy. H4: Fastboot/Recovery, bugreport, package deployment rollback, full lifecycle test execution and device hardware E2E.

Sources: [Android adb](https://developer.android.com/tools/adb), [Run tests with adb](https://developer.android.com/studio/test/command-line), [Logcat command line](https://developer.android.com/studio/command-line/logcat).

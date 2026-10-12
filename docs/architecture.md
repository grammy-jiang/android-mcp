# Architecture

## Topology

```text
                         ChatGPT / other MCP clients
                              |              |
                     secure endpoint   secure endpoint
                              |              |
     macOS or Linux host                          Dedicated Android tablet
   ┌─────────────────────────┐            ┌──────────────────────────┐
   │ Host MCP (Python)       │            │ Native MCP (Kotlin)      │
   │   tool router & policy  │            │   tool router & policy   │
   │   ADB/Fastboot adapter  │            │   Accessibility bridge   │
   │   diagnostics / deploy  │            │   screenshots / actions  │
   └───────────┬─────────────┘            │   optional privilege     │
               │ USB ADB/Fastboot         │   broker (local IPC)      │
               └─────────────────────────┤                          │
                                         └──────────────────────────┘
```

This is the **target privileged/remote topology**, not a claim that authenticated remote endpoints or the pictured Android privileged/UI components exist. A minimal Android foreground-only **localhost** APK prototype exists (N1), without the pictured elevated capabilities.

## Contracts, runtimes, and capabilities

- `contracts/`: JSON Schema is the wire-level source of truth. Keep the same `schema_version`, device descriptors, errors, and capability IDs on both runtimes.
- `host/`: ADB/Fastboot availability, device selection, APK lifecycle, Logcat, bugreports, instrumentation triggers, recovery.
- `android/`: local Android APIs, foreground service, Accessibility/UI, optionally privileged OS operations, long-lived app automation.
- Business-specific adapters such as shopping must live above the device controller and may be extracted later without changing low-level contracts.

A host server must start with *zero connected devices*. It must not manufacture device capabilities from OS detection alone. An Android native server should start with whatever permissions have actually been granted, not automatically infer root from a custom ROM.

## Device identity and operation routing

Every mutating operation (not yet implemented) must target one explicit `device_id`; multiple devices cannot silently fall back to the first result. USB serial, emulator serial and native installation identity may differ. A future pairing record must bind the host view to the native view without assuming they match byte-for-byte.

Per-device coordination:

- **Observe** may run concurrently when consistent with the device's security policy.
- **Mutate/UI** requires an exclusive, expiring device lease with a task owner, operation class, expiry and audit trail.
- **Maintenance** should quiesce the native UI executor before host ADB app reinstall/restart.
- **Recovery** may use host ADB even if the native service is unavailable; such forceful operations require a separately auditable approval path.

The lease mechanism should not depend on ChatGPT keeping one transport connection alive. Initially this is a design contract, not an implemented distributed lock.

## Whole Android development lifecycle

| Stage | Host | Native |
| --- | --- | --- |
| Provisioning and device discovery | ADB/Fastboot | local health |
| Build artifacts | host toolchain / external CI | not responsible |
| APK deploy and rollback | ADB install/uninstall | managed user-granted actions |
| UI and E2E testing | instrumentation trigger, logs | Accessibility, screenshot, gestures |
| Diagnostics and performance | Logcat, dumpsys, bugreport, Perfetto | local scoped diagnostics |
| System/ROM engineering | Fastboot/recovery when available | optional privilege broker |
| Boot failure recovery | external host | unavailable if Android not running |
| Shopping workflows | no business logic | app adapters after core gates |

## Execution and lifecycle

Current Host MCP registers exactly three tools: `device_status`, `adb_observe`, and `adb_develop`. Diagnostics and allowlisted observations are read-only; executed APK installation/instrumentation is disabled in the default composition. `doctor` does not require ADB to succeed. The Host server listens only on localhost, and subprocess invocation uses bounded argument vectors without a host shell.

The current N1 Native Android prototype starts a loopback-only MCP endpoint when its activity is foregrounded, and stops when that activity stops. A durable Native service, external caller authentication and user-granted UI control are future work. The design requires Native to function independently of Host connectivity; Host recovery remains a separately gated capability.

## Explicit non-goals of the scaffold

No completed Native **real-device APK acceptance**, root activation, Device Owner provisioning, authenticated public endpoint, shopping automation, enabled distributed mutation authority, or changes to Binnacle. Host read-only ADB has been accepted against a real USB tablet on sextant.

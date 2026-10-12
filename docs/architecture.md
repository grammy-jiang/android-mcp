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

This is a diagram of the **target topology**, not a claim that either remote endpoint or the Android APK currently exists.

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

For current Host MVP, `device_status` is the only MCP tool. `doctor` reports diagnostic state without requiring ADB. Server listens only on localhost. Portable code uses argument-vector subprocess calls and no shell to invoke ADB.

For the future Native runtime: lifecycle is controlled by Android components rather than a desktop CLI; network access must be separately authenticated. Native must function without host connectivity. Host can bootstrap/recover native but must never be required for its normal operation.

## Explicit non-goals of the scaffold

No installed tablet, no Android APK, no root activation, no Device Owner provisioning, no open remote endpoint, no e-commerce account automation, no code or configuration changes to Binnacle.

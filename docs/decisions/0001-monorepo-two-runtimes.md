# ADR 0001 — One repository, two independent MCP runtimes

- **Status:** Accepted for initial scaffold
- **Date:** 2026-10-12

## Context

Android engineering spans UI automation within the device and ADB/Fastboot operations that depend on a working external host. A dedicated tablet can run its own MCP service; it is also physically attachable to a macOS/Linux computer. Binnacle's generic host file/command functions have a different domain and permission model.

## Decision

Maintain one `android-mcp` repository with:

- `host/`: Python/FastMCP, macOS and Linux, Android Platform Tools.
- `android/`: Android/Kotlin runtime, to be implemented.
- `contracts/`: platform-neutral capabilities and message schemas.
- `docs/` and cross-platform CI.

The two runtimes are separate processes/endpoints and can be running simultaneously. They share protocol/data contracts, but **neither is an availability dependency of the other**.

Use feature/permission detection rather than assuming an OS or ROM grants a capability. Reserve a recovery channel through external ADB/Fastboot.

## Consequences

- One versioned codebase, potentially separately releasable host package and APK.
- Host and native code may use different implementation languages and test tools.
- Two independent authentication boundaries and a device-operation conflict policy are necessary.
- App-specific automation (shopping) must stay outside the core device transport.
- Device-independent CI can begin before the physical tablet is connected.

## Rejected

1. Adding Android functionality directly to Binnacle (domain and dependency coupling).
2. Two unrelated repositories (contract drift).
3. A single process that needs a working host and tablet together (poor availability).
4. Making arbitrary root/ADB shell available as a default internet-facing MCP tool.

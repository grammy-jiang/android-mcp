# Implementation plan and acceptance gates

## Current status (2026-10-12)

**M0/Q1** quality baseline merged. **Host H1/H2/H3 release candidate** includes explicit-device read-only observation, bounded typed ADB diagnostics, and *non-activated* signed-grant/local-lease/audit prototypes. On 2026-10-12, Host MCP over localhost Streamable HTTP passed **real USB** read-only acceptance on sextant (Linux ARM64) against an authorized OnePlus Pad 3 (Android 16), and macOS/Linux development gates passed. The hardened CI matrix includes Python 3.11/3.13/3.14, packaging, static security and dependency audits; see [Host acceptance](host-live-acceptance.md). The MacBook's own direct USB connection awaits macOS accessory authorization. Host↔Native coordination, external authenticated access and the Kotlin Native APK remain unimplemented/unverified.

## Parallel workstreams with explicit I/O

| Stream | Inputs | Output | Gate / tests | Dependencies |
| --- | --- | --- | --- | --- |
| C — contracts | `docs/contracts.md`, status schema | versioned JSON schema and fixtures | `host/tests/test_contract.py` | none |
| H — host | schema, official ADB CLI | Python Host MCP, doctor, typed ADB operations (later) | unit mocked subprocess and live Mac/Linux integration | C |
| N — native | schema, Android SDK capability inventory | Kotlin APK Native MCP, Accessibility, task state (later) | Android instrumented tests | C |
| S — security | `docs/security.md` | operation policy, auth, privilege broker threat model | negative authorization tests | C |
| E — E2E | H and N build outputs | remote ChatGPT ordinary Chat handshake/screenshots; device handoff | two live endpoints + screenshot pixels verified | H, N, S |
| B — business | stable native UI API | shopping adapters and evidence extraction | platform-specific live app tests | E |

### Milestones

The H1/H2/H3 candidate is pre-hardware and must pass macOS/Linux/CI and independent security review before any device-mutating execution. It does not replace M2/M3/M5 acceptance gates.

- **M0** (this scaffold): private repository, Host read-only status, no-device tests, Mac/Linux CI, draft Android architecture and security; locked lint/type/coverage checks, Git hooks, developer doctor, package smoke and scheduled audits.
- **M1**: gated Host ADB capabilities: explicit serial, validated read-only diagnostic operations, stable errors/timeouts, Linux USB permission guidance; separate tests.
- **M2**: minimal Kotlin Android Native MCP (no root), real UI/screenshot observation, App lifecycle.
- **M3**: independently authenticated MCP endpoints tested in ChatGPT ordinary Chat; return rendered screenshots and real UI info.
- **M4**: Host typed APK/deploy/logcat/instrumentation; Native UI actions; privilege broker prototype (only if justified by actual ROM capabilities).
- **M5**: paired device identity, distributed control lease, recovery, device reboot/USB/Wi-Fi reconnect tests.
- **M6**: Android development lifecycle acceptance matrix: build deployment, install, test, collect logs, trace performance, debug, restore.
- **M7**: shopping adapters for Taobao, Goofish and JD built on Native Runtime.

## Test execution policy

Run affected unit tests for each workstream change. At merge/release gates, run locked Ruff, strict mypy, Bandit, branch coverage policy, contract and fault tests, distribution smoke, secret scanning and the cross-platform CI matrix. Real-device tests remain separately gated, and cannot be replaced by mock-only claims.

## First device session checklist

Read real `adb devices -l`, model, Android version, build type, SELinux, optional root/bootloader state *without changing them*. Measure screen capture, UI tree, latency and app compatibility. No rooting, flashing, user data clearing, or Device Owner changes without a separate reviewed plan.

## Explicit non-goals

No Android Native pairing or APK deployment in this Host release, no remote MCP tunnel/auth claim, no Binnacle changes, no shopping account actions, no public repository publishing.

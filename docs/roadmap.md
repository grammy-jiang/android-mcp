# Implementation plan and acceptance gates

## Current status (2026-10-12)

**M0** foundational repository, Host quality-gate infrastructure and development standards only. The Android tablet is not attached. The new host MCP has read-only discovery, a CLI/doctor, isolated ADB subprocess provider, contract fixtures, cross-platform automated tests, and documentation. Everything beyond that is a roadmap, not an implemented claim.

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

No tablet pairing today, no Android app implementation today, no remote MCP tunnel/auth claim today, no Binnacle changes, no shopping account actions, no publishing a public repository.

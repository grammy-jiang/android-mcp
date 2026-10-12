# Android MCP

A **single repository with two independent MCP runtimes** for Android engineering:

- **Host runtime** (`host/`): Python + FastMCP on macOS and Linux, using Android Platform Tools (ADB / later Fastboot).
- **Native runtime** (`android/`): a Kotlin Android foreground-only loopback MCP app prototype; wider supported Android APIs, Accessibility and an optional isolated privilege broker remain future gated work.

The runtimes share *contracts*, security rules, release intent, and tests—not a mandatory live network dependency. The host can recover the tablet if the native service is down; the native service can operate without the host.

> **Status (2026-10-12, after PR #13):** Three read-only Host MCP tools have passed localhost HTTP → USB ADB acceptance on a Linux ARM64 Raspberry Pi and an authorized tablet. APK installation/instrumentation can be planned but **cannot execute in the production Host composition**. The Kotlin Native N0 JVM prototype and N1 Android foreground-only localhost APK scaffold are merged; the N1 APK is **not yet validated on the real tablet**. There is no authenticated external endpoint, completed joint Host/Native lease, shopping adapter or root broker.

## Host quick start

Prerequisites: macOS or Linux, Python 3.11–3.14, and [uv](https://docs.astral.sh/uv/). ADB is optional for starting the server; without it, status explicitly reports the missing dependency.

```bash
python3 scripts/dev.py bootstrap
python3 scripts/dev.py doctor --require-hooks
uv run --project host --locked android-mcp-host doctor
uv run --project host --locked android-mcp-host serve
```

The host MCP endpoint is **localhost-only**: `http://127.0.0.1:8765/mcp/`. It has **no built-in remote access/authentication in this scaffold**. Do not expose it directly to a network or the public internet.

To run the complete Host checks (lint, strict types, security, branch coverage and contract tests):

```bash
python3 scripts/dev.py check
```

The quality policy independently enforces **statement and real branch coverage** per production module. Host CI covers Ubuntu/macOS and Python 3.11/3.12/3.13/3.14; repository hygiene runs for every PR, and a separate weekly dependency audit runs on the default branch. Hardware-free tests do not need Android Platform Tools or a physical device.

Current Host MCP tools:

| Tool | Status | Purpose |
| --- | --- | --- |
| `device_status` | Implemented, read-only | Host OS/architecture, ADB availability, connected device states, and diagnosed errors |
| `adb_observe` | Implemented; device required | Allowlisted system/boot/battery/display/storage/SELinux/identity/package observations |
| `adb_develop` | Implemented; device required | Bounded package diagnostics, Logcat snapshots, preview of APK install/instrumentation (actual mutations blocked by default) |
| Native UI/privileged tools | Planned | Android-only services with separate permission controls |

## Repository map

```text
android-mcp/
├── contracts/           # Shared transport-neutral JSON Schema
├── host/                # Python/FastMCP, macOS + Linux
│   ├── src/android_mcp_host/
│   └── tests/
├── android/             # Kotlin protocol + foreground-only local APK prototype
├── docs/                # Architecture, compatibility, security, milestones, ADRs
├── scripts/             # Cross-platform developer checks
└── .github/workflows/    # Host, Native, repository hygiene and security CI
```

## Platform model

The same repository is used on every machine. On macOS/Linux, start the Host executable. On Android, the current N1 APK can start a **foreground-only localhost listener** when the user explicitly opens and starts it; it stops with the activity. A durable Android service lifecycle is not yet implemented. Do **not** try to run a desktop Python binary as an Android background service.

The host and native servers are separately addressable MCP endpoints, with capability discovery and explicitly selected devices. No hardware needs to be connected to build, test, or read this repository.

## Scope

This repository is **independent of Binnacle**, and must not mutate Binnacle's repository or deployment. Later modules may cover the Android software lifecycle (APK deployment, logs, tests, performance, system maintenance, recovery) and a shopping automation adapter for Taobao, Goofish, and JD. Those domains must remain isolated from the core Android device transport.

See [Host integration verification](docs/host-integration-verification.md), [Host/Native coordination design](docs/host-native-coordination.md), [architecture](docs/architecture.md), [development](docs/development.md), [quality](docs/quality.md), [testing](docs/testing.md), [compatibility](docs/compatibility.md), [security](docs/security.md), [contracts](docs/contracts.md), and [milestones](docs/roadmap.md).

中文概览：这是一个 Monorepo、两个独立 MCP Runtime。Host 已在 Linux ARM64 的 sextant 节点经 USB 对真实平板完成只读 MCP 验收；设备修改功能仍默认禁用。Native 已合入 Kotlin JVM 原型和前台 localhost 调试 APK 框架，但尚无真实平板上的 APK 验收、外部认证服务、联合 Lease、Root Broker 或购物适配器。

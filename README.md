# Android MCP

A **single repository with two independent MCP runtimes** for Android engineering:

- **Host runtime** (`host/`): Python + FastMCP on macOS and Linux, using Android Platform Tools (ADB / later Fastboot).
- **Native runtime** (`android/`): a future Android/Kotlin application operating locally through supported Android APIs, Accessibility, and an optional isolated privileged broker.

The runtimes share *contracts*, security rules, release intent, and tests—not a mandatory live network dependency. The host can recover the tablet if the native service is down; the native service can operate without the host.

> **Status (2026-10-12):** Host H1/H2/H3 integration candidate. Three Host MCP tools are available; observe/package/logcat operations require a connected authorized Android device. Install/instrument commands can be planned but are **disabled for actual execution** until a trusted operator grant, durable audit and Host↔Native joint lease are implemented and independently verified. There is no Android APK, shopping adapter, root broker or remote authentication yet.

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

The quality policy is fail-closed for every production module. CI covers Ubuntu/macOS and Python 3.11/3.13/3.14. Hardware-free tests do not need Android Platform Tools or a physical device.

Current MCP tool:

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
├── android/             # Android Native MCP design; APK not implemented
├── docs/                # Architecture, compatibility, security, milestones, ADRs
├── scripts/             # Cross-platform developer checks
└── .github/workflows/    # macOS + Linux host CI
```

## Platform model

The same repository is used on every machine. On macOS/Linux, start the Host executable; on Android, the eventual APK starts the native runtime using Android's own service lifecycle. Do **not** try to run a desktop Python binary as an Android background service.

The host and native servers are separately addressable MCP endpoints, with capability discovery and explicitly selected devices. No hardware needs to be connected to build, test, or read this repository.

## Scope

This repository is **independent of Binnacle**, and must not mutate Binnacle's repository or deployment. Later modules may cover the Android software lifecycle (APK deployment, logs, tests, performance, system maintenance, recovery) and a shopping automation adapter for Taobao, Goofish, and JD. Those domains must remain isolated from the core Android device transport.

See [Host integration verification](docs/host-integration-verification.md), [Host/Native coordination design](docs/host-native-coordination.md), [architecture](docs/architecture.md), [development](docs/development.md), [quality](docs/quality.md), [testing](docs/testing.md), [compatibility](docs/compatibility.md), [security](docs/security.md), [contracts](docs/contracts.md), and [milestones](docs/roadmap.md).

中文概览：这是一个 Monorepo、两个独立 MCP Runtime。Host 已实现只读 ADB 观察与受限开发命令规划，以及默认关闭的高权限执行原型；尚未连接真实平板，也没有 Android Native APK、Root、购物适配器或公网服务。

# Android MCP

A **single repository with two independent MCP runtimes** for Android engineering:

- **Host runtime** (`host/`): Python + FastMCP on macOS and Linux, using Android Platform Tools (ADB / later Fastboot).
- **Native runtime** (`android/`): a future Android/Kotlin application operating locally through supported Android APIs, Accessibility, and an optional isolated privileged broker.

The runtimes share *contracts*, security rules, release intent, and tests—not a mandatory live network dependency. The host can recover the tablet if the native service is down; the native service can operate without the host.

> **Status:** early scaffold. The only implemented MCP operation is **read-only host/device discovery**. No device-changing commands, Android APK, shopping adapters, root broker, or remote authentication are implemented yet.

## Host quick start

Prerequisites: macOS or Linux, Python 3.11–3.14, and [uv](https://docs.astral.sh/uv/). ADB is optional for starting the server; without it, status explicitly reports the missing dependency.

```bash
uv sync --project host --locked --group dev
uv run --project host --locked android-mcp-host doctor
uv run --project host --locked android-mcp-host serve
```

The host MCP endpoint is **localhost-only**: `http://127.0.0.1:8765/mcp/`. It has **no built-in remote access/authentication in this scaffold**. Do not expose it directly to a network or the public internet.

To run the host checks:

```bash
./scripts/check-host.sh
```

Current MCP tool:

| Tool | Status | Purpose |
| --- | --- | --- |
| `device_status` | Implemented, read-only | Host OS/architecture, ADB availability, connected device states, and diagnosed errors |
| Typed ADB operations | Planned | Scoped, explicit-device actions; never unrestricted shell by default |
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

See [architecture](docs/architecture.md), [compatibility](docs/compatibility.md), [security](docs/security.md), [contracts](docs/contracts.md), and [milestones](docs/roadmap.md).

中文概览：这是一个 Monorepo、两个 MCP Runtime；电脑端专注 ADB/Fastboot，安卓端专注本机交互与可选高权限能力。当前仅实现电脑端只读诊断骨架，尚未接入实际平板、Root 或电商应用。

# ADR 0002 — Language, toolchain and enforceable quality policy

- **Status:** Accepted for Host; Native toolchain is a pending validated design choice
- **Date:** 2026-10-12

## Decision

1. Host: Python 3.11–3.14, FastMCP pinned in `host/pyproject.toml`, uv lock checked offline. Support macOS and Linux on ARM64 and common desktop architectures. Centralize subprocess wrappers; no OS-specific hardcoded path.
2. Native: Kotlin (Android SDK), Gradle Kotlin DSL, Android Accessibility API and an optional local privilege broker. No Python, Termux, ADB server or Binnacle is required for Native production operation.
3. Shared wire protocol: platform-neutral JSON Schema and fixture-based compatibility testing. Keep Python and Kotlin implementations separate so neither language becomes a runtime dependency of the other.
4. Host quality gates: strict mypy, Ruff, Bandit, unit/contract/negative/property tests, 95% per-module branch-inclusive coverage for critical modules and 90% for the remainder, physical 500-line module cap, cross-OS CI and clean-wheel smoke.
5. Native quality gates, once built: Kotlin formatting/detekt, Android Lint, JUnit with fake platform services, instrumentation/emulator tests, live ROM-specific acceptance, privileged-operation security review and reproducible APK build.

## Why not other languages?

- Java for Native has excellent Android support but adds boilerplate for coroutines, structured concurrency and service abstractions. Kotlin is the better Android-first default.
- Python for Native would add an interpreter/bridge, complicated background lifecycle, and insufficient direct access to protected Android APIs. It remains the better language for Host.
- A single common Kotlin Multiplatform binary for Host and Native is possible, but would give up the existing Python/ADB toolchain and introduce unnecessary platform abstractions.
- TypeScript for both runtimes adds Node dependency to the Android side and does not remove the need for Kotlin/Java system API integration.

## Native toolchain verification gate

As of 2026-10, Android Gradle Plugin 9.4 has a documented minimum **JDK 17** and requires Gradle 9.6. The official MCP Kotlin SDK supports Streamable HTTP via Ktor and is currently ranked Tier 3 in MCP SDK tiering. Its Android integration/foreground-service compatibility still requires a runnable device/emulator POC; **JVM/Kotlin support alone is not enough evidence**.

At M2, choose **exact**, tested AGP, Gradle, Kotlin, JDK, Kotlin MCP SDK and Ktor engine versions together, commit a Gradle Wrapper with verified checksum, verify dependency metadata/locking, and add Android CI. Do not commit a speculative `build.gradle.kts` that has not compiled.

Primary references:

- <https://developer.android.com/build/releases/agp-9-4-0-release-notes>
- <https://developer.android.com/build/releases/about-agp>
- <https://github.com/modelcontextprotocol/kotlin-sdk>
- <https://modelcontextprotocol.io/docs/sdk>

## Risk and future amendments

Current Python coverage thresholds apply only to production Host modules; adding permissions, leases or arbitrary device actions will require additional explicit policy categories and negative/concurrency tests. Do not use test percentage as a substitute for security review or actual device acceptance.

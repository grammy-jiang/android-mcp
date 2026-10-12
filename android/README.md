# Android Native MCP workspace

This is the **Android half of the same monorepo**, with a separate runtime and
permission boundary from the Python Host MCP.

## Current implementation

`native-protocol/` is a **pure Kotlin/JVM contract module**, buildable without
an Android SDK, emulator, connected tablet, Root or third-party app credentials.
It uses the repository's versioned JSON fixtures and tests the device-status
contract in a second language independently of the Host Python implementation.

> No APK or Android accessibility service is built by this module yet. A passing
> JVM test is **not** proof of Android background-service operation, MCP-over-HTTP
> compatibility, screenshot transport or Root access.

## Local development

Use Java 17 and the committed Gradle Wrapper. Run the repeatable test
entrypoint from the repository root. It validates the Kotlin contract unit tests
plus a real cross-language localhost MCP HTTP exchange from Python:

```bash
export JAVA_HOME=/path/to/jdk17
bash scripts/check-native.sh
```

The standalone Gradle commands remain available:

```bash
cd android
./gradlew --no-daemon :native-protocol:test
```

Once an Android app module is introduced, its build should use verified Android
SDK / AGP compatibility, Android Lint, emulator/instrumentation tests and an
independent permission-security review. The protocol module must remain free of
`android.*` package imports and Android process lifecycle assumptions.

## Planned boundaries

- An unprivileged network gateway handles MCP wire protocol, authentication
  and typed tool routing.
- An `AccessibilityService` (granted explicitly by the device user) exposes
  UI inspection, gestures and screenshots.
- A local privileged broker, **not** the public HTTP listener, may be added
  only after ROM/root privilege, SELinux and signed-request review.
- Host/Native lease coordination is specified in
  `../docs/host-native-coordination.md` on the Host H1–H3 review branch,
  and must be merged before enabling device mutation.

The Native runtime is expected to operate when no Host PC is attached.

## Local Kotlin MCP wire test

The `native-mcp-jvm` module runs a synthetic, read-only `device_status` tool
over loopback HTTP using the official Kotlin MCP SDK. It is **not** an Android
service; see `../docs/native-jvm-mcp-prototype.md`.

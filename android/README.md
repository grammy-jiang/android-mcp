# Android Native MCP workspace

This is the **Android half of the same monorepo**, with a separate runtime and
permission boundary from the Python Host MCP.

## Current implementation

`native-protocol/` is a **pure Kotlin/JVM contract module**, buildable without
an Android SDK, emulator, connected tablet, Root or third-party app credentials.
It uses the repository's versioned JSON fixtures and tests the device-status
contract in a second language independently of the Host Python implementation.

> N1/N2 now provide a buildable Android APK and validated Android 16 emulator
> MCP HTTP/lifecycle acceptance. N3 adds a separately opt-in user-visible local
> foreground-service prototype. **No Accessibility, Root, paired identity,
> authenticated remote listener, or real-tablet Native APK acceptance exists.**

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

The opt-in Android app uses verified SDK API 36, AGP 9.4, Android Lint and
an exact manifest-permission allowlist. Execute `bash scripts/check-native-apk.sh`
with an installed licensed Android SDK to build and verify its Debug APK.
Execute `bash scripts/check-native-emulator.sh` only against an explicit,
prestarted disposable `emulator-5554` Android 16 AVD; both test scripts enforce
`ro.kernel.qemu=1` before any emulator mutation. No real tablet is used.
The protocol module remains independent of Android process lifecycle.

## Planned boundaries

- An unprivileged network gateway handles MCP wire protocol, authentication
  and typed tool routing.
- An `AccessibilityService` (granted explicitly by the device user) exposes
  UI inspection, gestures and screenshots.
- A local privileged broker, **not** the public HTTP listener, may be added
  only after ROM/root privilege, SELinux and signed-request review.
- Host/Native lease coordination is specified in
  `../docs/host-native-coordination.md`; the design is not implemented
  and cannot authorize any device mutation.

The Native runtime is expected to operate when no Host PC is attached.

## Local Kotlin MCP wire test

The `native-mcp-jvm` module remains an SDK-free synthetic protocol proof.
See [JVM prototype](../docs/native-jvm-mcp-prototype.md),
[real Android N2 emulator acceptance](../docs/native-emulator-n2.md), and
[N3 user-started foreground service](../docs/native-foreground-n3.md).

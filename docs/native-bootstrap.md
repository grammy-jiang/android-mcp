# Native Kotlin build baseline (pre-device)

- Language: Kotlin 2.3.21 pinned in Gradle plugin.
- Build: Gradle 9.6.0 with a committed, SHA-256 checked wrapper.
- JVM: JDK 17; `native-protocol` compiles to JVM target 17.
- First module: pure protocol decoding/tests against shared
  `contracts/fixtures`. No Android SDK or hardware required to run tests.
- Planned APK: AGP 9.4, requires Gradle >=9.6 and JDK >=17
  (see [AGP 9.4 release notes](https://developer.android.com/build/releases/agp-9-4-0-release-notes)).
- Native on-device server: requires a separate Kotlin MCP SDK/Ktor embedded
  transport compatibility proof. Its SDK support for JVM targets alone is
  insufficient evidence of Android service stability.
- No default network exposure or Root; packaging, lease authority and Android
  lifecycle are unimplemented until their tests pass.

Do not embed Host private signing keys, cloud MCP credentials, ADB transports,
or shopping automation into the shared protocol DTO module.

# JVM-only Kotlin MCP protocol smoke

This module verifies that **the official Kotlin MCP SDK 0.14.0** can expose a
Streamable HTTP `device_status` tool on localhost. It uses Kotlin 2.3.21 and
Ktor CIO 3.4.3. It is **not** Android Native MCP.

- No Android device APIs or hardware; no Google SDK license needed.
- No AccessibilityService, foreground service, Root broker or app automation.
- No authentication, tunnel, pairing or permanent listener. The command binds
  `127.0.0.1` only and is for local disposable testing.
- Status contains **zero devices** and all capabilities false. The tool's
  description labels it synthetic; do not expose to a real ChatGPT connection.

Reproducible JVM-only protocol and localhost wire test (no Android SDK):

```bash
export JAVA_HOME=/path/to/jdk17
bash scripts/check-native.sh
```

The command runs Kotlin unit tests, launches a disposable loopback Kotlin MCP
process, then validates its `device_status` with a real Python FastMCP client
against the versioned shared JSON Schema. No actual device observations or
permissions are tested, and the test listener is always terminated.

Build/test on a Mac with JDK 17:

```bash
cd android
./gradlew --no-daemon :native-protocol:test :native-mcp-jvm:installDist
./native-mcp-jvm/build/install/native-mcp-jvm/bin/native-mcp-jvm 38765
```

In another terminal connect to `http://127.0.0.1:38765/mcp` with a standard
MCP client. Cross-language smoke should parse tool output against
`contracts/device-status.v1.schema.json`.

For Android APK use, build an independent `:app` module after Google Android
SDK license is explicitly accepted. The Kotlin MCP SDK's JVM compatibility
does not prove Android's foreground/background lifecycle or Ktor CIO support
on the ROM.

The Gradle wrapper is pinned to 9.6.0 and verifies the official SHA-256.

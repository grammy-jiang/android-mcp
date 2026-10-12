# H2.a — Host Android SDK/NDK/JDK workstation prerequisites

This is an **opt-in**, non-mutating Host-side inventory. It is not a build,
deployment, license acceptance, Android device action or authenticated network
interface. Start the optional MCP Tool locally with:

```sh
uv run --project host --locked android-mcp-host serve --sdk-ndk-inventory
```

The default FastMCP server **still exposes exactly the original three
public v1 Tools**. The new `host_sdk_ndk_inventory` Tool accepts no
arguments, paths, executable overrides, package manager commands or
license-consent flags. It publishes the Host-only packaged JSON Schema
`urn:android-mcp:host-sdk-ndk-inventory:v1`.

## Independent readiness facts

Nine separate typed records report `state`, `reason`, `version`,
`installed` and `runnable`:

| Record | Fixed, bounded verification |
| --- | --- |
| `jdk17` | Trusted fixed Java binary and exact JDK 17 version |
| `sdk_platform` | Android API 36 platform's nonempty, structurally valid `android.jar` ZIP |
| `build_tools` | Android Build Tools 36.0.0 metadata and aapt2/apksigner/zipalign/d8 executable markers |
| `gradle` | Fixed Gradle installation version 9.6 or later |
| `emulator` | SDK-local Emulator version-only query |
| `ndk` | SDK-local NDK revision metadata matching folder and fixed host-compatible Clang version |
| `cmake` | SDK-local CMake binary version matching installed folder |
| `apkanalyzer_sdk` | SDK-local analyzer version probe |
| `apkanalyzer_homebrew` | Independently checked Homebrew analyzer; broken CLI is `installed_unusable` |

Missing, partially installed, unsuitable, untrusted symlink or
wrong-version components remain unavailable with explicit typed reasons.
A broken Homebrew analyzer never invalidates an independently valid
SDK-local analyzer. NDK host tags require the **actual** macOS/Linux
architecture; an ARM64 Pi is not assumed to support an x86_64 NDK binary.

Host-approved fixed directories are used, not arbitrary caller-selected
locations or shell `PATH`. The SDK root defaults to
`~/Library/Android/sdk` on macOS and `~/Android/Sdk` on Linux.
All SDK descendants are checked for symlink escape and bounded directory
enumeration (64 entries). Source metadata is bounded to 8 KiB.
The existing process-group-managed bounded runner now supports an explicit
subprocess environment. SDK/NDK/JDK/Gradle version probes use a **minimal
allowlisted child environment**, removing inherited `JAVA_HOME`,
`JAVA_TOOL_OPTIONS`, `ANDROID_HOME`, `GRADLE_USER_HOME`,
`LD_PRELOAD` and hostile `PATH`. No shared process environment is mutated.
Each CLI probe uses a fixed argv tuple, three-second default timeout and a
64 KiB combined output limit; child process groups are reaped on timeout
or excessive output. No arbitrary Gradle task or SDK package manager
invocation is ever created.

The result's `build_prerequisites_present` flag checks **only local
observed prerequisites** (JDK 17, SDK 36, Build Tools 36 and Gradle >=9.6).
It does **not** attest package licensing, wrapper integrity, compatible
AGP, Gradle project selection, account grants or a successful build.
`sdk_licenses_verified` and `build_authorized` are always **false**;
those separate verification/authorization gates belong to later packages.
Version probes may touch Host-local tool caches; the metadata advertises
`readOnlyHint: false` conservatively, with `destructiveHint: false`.

Tests T-H2A-01–06 and extensive negative-path tests use synthetic SDK
markers, executable fakes, malformed metadata, hostile child environments,
cross-platform versions, timeouts, output overflow, real process reaping,
in-process FastMCP Schema and localhost HTTP. This is no evidence of actual
Android device control, SDK agreement acceptance or store publishing.

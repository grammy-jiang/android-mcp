# H2.b — pinned Android Gradle build preflight (plan only)

H2.b adds an operator-opted-in `android_build_preflight` FastMCP Tool.
It **never executes Gradle** (including `gradlew --version`), downloads
dependencies, installs an APK, changes a device, accepts SDK licenses,
signs a binary, or modifies a Git worktree. The normal Host server retains
its original three v1 Tools unless an operator deliberately enables this
new, separately versioned capability.

The Host operator, **not the MCP caller**, selects one absolute trusted
Git repository root and two explicit pins:

```sh
uv run --project host --locked android-mcp-host serve \
  --build-preflight \
  --build-root /trusted/checkout/android-mcp \
  --build-approved-revision FULL_40_CHARACTER_GIT_SHA \
  --build-wrapper-sha256 FULL_64_CHARACTER_SHA256
```

When either pin is absent, every request is denied with
`UNAPPROVED_PIN`. MCP callers cannot supply an executable, project
path, Git revision, Gradle task, script or additional flags. They can
choose only `assemble_debug`, `lint_debug`, or `test_jvm`; the
`variant` is fixed to `debug`. Action lists are compiled exclusively
from a static allowlist. No release signing/publishing action is
accepted.

The preflight verifies an absolute nonsymlink project root with no
`..` components and at most 1,024 path characters. It examines only
a bounded set of hard-coded files under that root, checking all ancestor
components for symlinks. It requires an executable `android/gradlew`
launcher, a bounded real ZIP-format Gradle wrapper JAR containing
`GradleWrapperMain.class`, and its exact operator-approved SHA-256.
The `gradle-wrapper.properties` file must pin the HTTPS Gradle 9.6.0
distribution and a full 64-character distribution checksum, enable
URL verification and disable automatic retries. Static Android build
metadata must match the approved AGP 9.4.0, API 36, Java 17
configuration and opted-in `:app` inclusion.

Only two fixed read-only Git invocations are permitted: `rev-parse
--verify HEAD` and `status --porcelain=v1 --untracked-files=all`.
They use the fixed `/usr/bin/git`, a minimal child environment,
`GIT_OPTIONAL_LOCKS=0`, system/global config disabled, fsmonitor
disabled and a fixed hooks path. Output/timeouts are bounded with
process-group cleanup. A missing, malformed, unapproved revision,
uncommitted change, Git error or overflow **blocks** the plan. Nothing
is stashed, reset, checked out or cleaned, and the repository remains
untouched. The tool reports whether the original checkout was dirty,
without exposing changed filenames or Git stderr.

The Host SDK/JDK/Gradle inventory is then queried independently. JDK 17,
SDK API 36, Build Tools 36 and the supported Gradle 9.6 version must
all be reported runnable; incomplete or malformed provider reports
fail closed. The resulting v1 Schema
`urn:android-mcp:host-android-build-preflight:v1` records the trusted
root, expected and observed Git SHA, validated wrapper and
distribution checksums, pinned Android/AGP/JDK versions, cleanliness,
approved task IDs and a bounded **inert argv preview**.

Importantly, `execution_enabled` and `sdk_licenses_verified` are
**always false**, even for a successful `planned` result.
This is **not a build authorization or a guarantee** that dynamic
Gradle logic, dependencies, environment state or future hardware
operations are safe. The later H2.f execution gate must independently
revalidate the exact project files, Git pins, SDK licensing and other
approvals at execution time; a preflight result must never become a
privilege grant.

H2.b tests T-H2B-01..06 and supplemental tests exercise synthetic
approved/invalid trees, real throwaway Git repositories (including
uncommitted changes and index-lock noninterference), hostile path
components, unexpected CLI errors/timeouts and process cleanup,
FastMCP in-process metadata/JSON Schemas and localhost HTTP with
injected synthetic providers. No production Android device, third-party
checkout, Gradle build or SDK agreement was modified or executed.

# Native N3 Gradle dependency integrity and reproducibility

**Scope:** Kotlin/Android build dependencies. This is not runtime caller
authentication, APK signing trust, or Host/Native authorization.

## Current implementation

- Gradle Wrapper 9.6.0 has a pinned distribution SHA-256.
- AGP 9.4.0, Kotlin 2.3.21, official Kotlin MCP SDK, Ktor and direct library
  coordinates remain explicitly versioned in their module build scripts.
- The Native root Gradle build enables `dependencyLocking { lockAllConfigurations() }`
  for all subprojects, including the opt-in Android app module.
- Four committed `android/*/gradle.lockfile` files pin actually resolved
  transitive versions for the current build/test configurations.
- `android/gradle/verification-metadata.xml` records SHA-256 for artifacts and
  Maven metadata resolved on the developer Mac (316 components, 540 hashes
  at the first 2026-10-12 generation). These hashes are a reviewed
  **trust-on-first-use snapshot**, not third-party provenance attestation.
- `scripts/audit_native_gradle_policy.py --strict` provides a bounded
  static preflight for pinned versions, repository policy, lockfiles and
  checksum metadata. It does not replace Gradle's actual verification.

## Validation

From repository root, with JDK 17 and installed licensed Android SDK 36:

```bash
python3 scripts/audit_native_gradle_policy.py --strict
bash scripts/check-native.sh
bash scripts/check-native-apk.sh
```

On the original Apple Silicon Mac, the following full task graph succeeded
**offline with Gradle dependency verification in strict mode**:

```bash
./android/gradlew --project-dir android --offline --no-daemon \
  --dependency-verification=strict -PenableAndroidApp=true \
  :app:assembleDebug :app:lintDebug :native-protocol:test \
  :native-lifecycle:test :native-mcp-jvm:installDist
```

The Gradle lockfiles are still required at build time; the dependency
metadata alone does not freeze version resolution. Do not add Gradle
`--write-locks` or `--write-verification-metadata` to normal CI because
those commands **mutate the approved baseline**.

## Updating dependencies

1. Open a separate short Native PR, inspect its direct and transitively
   resolved dependency differences and source repositories.
2. In a controlled environment with authorized network access, run the
   affected Gradle tasks with `--write-locks` and regenerate checksum
   metadata with `--write-verification-metadata sha256`.
3. Review **all** newly trusted checksums against source integrity evidence
   where available. Do not blindly trust regenerated hashes; do not disable
   dependency verification to make a build pass.
4. Run the SDK-free Native JVM gate, APK/Lint/permissions gate and the
   cross-API emulator matrix. Record exact SHA/test evidence.
5. Recheck clean Linux and macOS dependency resolution. Current metadata was
   created on Apple Silicon and may need separately reviewed platform-specific
   artifact checksums for Linux; do not claim portability without that test.

## Boundaries

The Gradle static script reports only policy metadata presence. A green
static check is not proof that a complete clean-room build on every platform
passed, nor is a successfully verified downloaded artifact proof of
nonmalicious upstream code. GitHub-hosted Actions may be blocked by the
account spending cap; report that as `not_run`, not as a test failure or
successful CI. Prefer local Mac/Pi evidence without increasing GitHub costs.

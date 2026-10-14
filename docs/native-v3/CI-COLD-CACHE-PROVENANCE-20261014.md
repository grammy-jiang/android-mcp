# Native V3 CI cold-cache verification and Git ancestry repair

**Engineering scope:** reproduce real CI infrastructure failures without
bypassing Gradle dependency verification or claiming Android product acceptance.

## Independently reproduced defects

1. Kotlin Linux/macOS GitHub Actions jobs failed before tests because the
   cold runner resolved `kotlinx-coroutines-bom:1.8.0.pom` without a SHA-256
   entry. The separately pinned `junit-bom:5.13.4.pom` was also missing,
   visible through `--refresh-dependencies` in a clean configuration phase.
2. Refreshing the Android app/fixture build and actual Lint dependencies
   revealed the additional absent `guava-parent:33.4.0-jre.pom`,
   `junit-bom:5.10.2.module`, `junit-bom:5.11.0-M2.module`, and
   `groovy-bom:4.0.29.pom` checksums. These are **existing pinned
   dependency graph artifacts**, not newly selected dependency versions.
3. The original mocked AVD ownership tests used the developer's literal
   hostname `Mac`. Automated Linux and hosted macOS runners use distinct
   machine names, so six honest ownership-unit tests failed even when
   actual signature and boot checks were correct. The tests now bind
   their **synthetic positive owner fixture** to `socket.gethostname()`;
   negative tests still deny mismatched Host identity. Production
   verification continues to require exact local hostname equality.
4. The Android emulator workflow checked out Git history at the default
   depth of one commit. `test_native_capability_ledger.py` verifies the
   38 older merged work-package SHAs using actual `git show` and
   `git merge-base --is-ancestor`, so a shallow GitHub Actions checkout
   can never satisfy the contract even when the underlying repository is sound.

## Fixed verification boundaries

Seven new SHA-256 entries were added, all cross-checked against
Maven Central's published .sha256 (where available), a separately fetched
complete upstream artifact, and the previously cached file on the Mac.
Six Maven Central artifacts and one Google Maven Linux-specific Android
resource-compiler JAR were independently checked using their official SHA256
endpoints and separate downloads. Their exact artifact hash/provenance is
enforced by `tests/test_native_v3_ci_coldcache_provenance.py`.

| Artifact | Independently verified SHA-256 |
| --- | --- |
| kotlinx-coroutines-bom-1.8.0.pom | `1239e9dbe1397cd5971342956b2511bc3ace7b641842e4372a088dcfa8b9ad55` |
| junit-bom-5.13.4.pom | `d7a08a99b2502f0bb68cd4e1f984f0bf69324aaa208bd0f73366c03fc3548a42` |
| guava-parent-33.4.0-jre.pom | `3a499ed34a0d9ee0f1bcc39230021a1cd4e2f7dd0426ab6844f585465d41dcd7` |
| junit-bom-5.10.2.module | `de23b114b3e4119a8fe6eb17bed5a3852816698bace67071579d6d927ebb080a` |
| junit-bom-5.11.0-M2.module | `86477abcf490d6ca059aa9973cb108d22a506f49d1a5569bb32cc6cbf43c2cce` |
| groovy-bom-4.0.29.pom | `c24277dec93f146bcda25f5ae4391d6527e384e2132efa32184c1e852b42bca9` |
| Google Android aapt2-9.4.0-15978811-linux.jar | `f5bebd466ecf14d341fd465f2756a16d86052f29eb4532003d5ff7bcffd08de5` |

No wildcard trust rule, unsigned artifact bypass, dependency update,
`--write-verification-metadata` shortcut, or disabled dependency integrity
check was introduced. Only the exact independently checked component files
receive SHA-256 pins.

The first implementation attempted to set `fetch-depth: 0` in two existing
GitHub Actions workflows, but **GitHub refused the local OAuth app to push
workflow file edits without the `workflow` scope**. We deliberately did not
refresh permissions, switch credentials, or push changed workflow files.
Those workflow edits are not part of this delivery and remain blocked by
external repository credential scope.

Instead, a narrow `native_v3_ci_git_history` helper is used by the
existing **strict** historical merge-receipt test itself. A normal local
checkout does nothing. Only in a verified shallow GitHub Actions checkout
for the exact `grammy-jiang/android-mcp` repository with a matching official
HTTPS origin does it fetch the previously omitted commits with
`git fetch --unshallow --no-tags --filter=blob:none origin`. It then
**requires** the repository to report non-shallow status before running
all original `git show` and `git merge-base --is-ancestor` checks.
Any missing history, wrong origin, untrusted fork, disallowed environment,
failed fetch or still-shallow checkout is a test failure, not a skip.

A behavioral regression uses a real disposable three-commit Git clone to
prove depth-one Git history cannot verify ancestry; it also exercises
failed/untrusted fetches without reaching other hosts. The Native baseline
merge-receipt checks are neither removed nor weakened.

## Local independent engineering gates

From the isolated CI repair worktree with the pinned Android SDK36
and JDK17:

```bash
uv run --project host --locked --group dev --python 3.13 \
  python -m unittest discover -s tests \
  -p test_native_v3_ci_coldcache_provenance.py -v
./android/gradlew --project-dir android --no-daemon \
  --no-configuration-cache --refresh-dependencies \
  :native-protocol:test :native-lifecycle:test :native-mcp-jvm:test
./android/gradlew --project-dir android --no-daemon \
  --no-configuration-cache --refresh-dependencies \
  -PenableAndroidApp=true -PenableV3Fixtures=true \
  :app:assembleDebug :app:lintDebug \
  :native-v3-fixture:assembleDebug :native-v3-fixture:lintDebug \
  :native-v3-install-fixture:assembleDebug
python3 scripts/audit_native_gradle_policy.py --strict
uv run --project host --locked --group dev --python 3.13 \
  python -m unittest discover -s tests -p 'test_native_v3_ci*.py'
bash scripts/check-native-local-ci.sh
```

The Gradle JVM refresh and Android/fixture/Lint refresh both genuinely
resolved successfully after the seven exact pins were included. The existing
Android Native tool catalog, Android manifest permissions, Host production
source, sensitive N01–N20 capability status and V3 acceptance evidence
are unchanged.

**Scope caveat:** GitHub's automatic PR/push Actions may still run according
to repository policy; no paid workflow was manually dispatched. This patch
does not assert that a green cloud workflow replaces independent signed
Android effects or actual N17 user consent. The E01.f integration gate
remains product-incomplete until feature-level tests pass.

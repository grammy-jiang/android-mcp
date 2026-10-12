# Native N3-05/06 offline continuation — 2026-10-12

**State:** Draft helper prepared away from MacBook because the MacBook Pro MCP and GitHub connectors were not exposed in this chat. It is **NOT** installed into the remote Native worktree and **NOT** validated against actual Android devices in this turn.

## Last verified live progress (previous connected turn)

- Native worktree: `/Users/grammy-jiang/Projects/android-mcp-native-setup`.
- N3 branch: `feature/native-n3-user-foreground-service`, latest checked local commit `7076d77d78587c57845ebd210e2d84a671b4795c`; N3-05 changes uncommitted.
- PR #16 still Draft, previous GitHub CI did not include new commits.
- Local Mac emulator image/AVD targets: API30 `emulator-5560`, API33 `emulator-5558`, API34 `emulator-5556`, API36 `emulator-5554`.
- Android 11/API30: N2 MCP PASS, N3 disabled with explicit warning, no N3 service.
- Android 13/API33: same PASS; discovered and fixed `NativeMcpActivity.onStop()` unintentionally re-enabling N3 button.
- Android 14/API34: both N2 and N3 PASS (at time of previous test); latest rebuild after API33 bug fix not yet independently retested on API34/36.
- Pure Python simulator guard tests 60/60 PASSED; Kotlin gate tests PASSED; locally built API36 debug APK/Lint/permissions PASSED at previous session.

## This independent patch

- Adds `scripts/verify_native_api_matrix.py`, an opt-in wrapper that **requires all 4 explicit serials**; validates `adb get-state`, `ro.kernel.qemu=1`, expected SDK API and `sys.boot_completed=1` on all targets **before any APK install**. It invokes only the already established scripts for the corresponding API and requires their explicit `result=pass` responses.
- Adds `android/tests/test_native_api_matrix_harness.py`, offline negative tests for incorrect/physical serials, API mismatch, offline/unfinished emulator, unique serials, and preflight-before-mutation.
- Does **not** add Gradle lock metadata by guessing transitive dependencies. That portion of N3-06 requires live Gradle resolution, verification metadata review, and build/CI enforcement after Mac connectivity returns.

## When the MacBook connector returns

1. Read current worktree `git status -sb`, `git rev-parse HEAD`, `git fetch origin main`, and PR #16 checks. **Never erase or stash uncommitted N3-05 changes.**
2. Confirm none of the patch's two file paths already exist. Copy them into the Native worktree; do not blindly apply if paths are occupied.
3. Run `uv run --project host --locked --group dev ruff check` and `ruff format --check` on both new Python files; then `uv run --project host --locked --group dev pytest -q android/tests`.
4. Run `bash scripts/check-native-apk.sh` with the already accepted Android SDK/JDK17.
5. If all four Android AVDs are running, verify the full matrix with:

```bash
uv run --project host --locked --group dev --python 3.13 python \
  scripts/verify_native_api_matrix.py \
  --api30 emulator-5560 --api33 emulator-5558 \
  --api34 emulator-5556 --api36 emulator-5554 \
  --apk android/app/build/outputs/apk/debug/app-debug.apk
```

1. If the matrix is green, stage *only* N3-05-specific files and commit a narrow checkpoint. Do not mark N3-06/N3-07 or PR #16 finished without actual remote Android and CI evidence.
2. For N3-06, inspect the real Gradle resolved dependency graph and generate/verify lockfiles and dependency-verification metadata from a clean, reviewed dependency baseline; no license acceptance or device changes are needed.

The runner never picks the first ADB device. Every child smoke rechecks emulator identity. Although the wrapper is designed for disposable AVDs, it does install an APK **in those explicitly validated virtual devices** when executed; this is outside the scope of physical OnePlus Pad 3 permissions.

## N3-06 dependency-policy static preflight (also in this patch)

- `scripts/audit_native_gradle_policy.py` checks for a pinned Gradle distribution SHA-256 and official HTTPS Gradle URL, fixed Gradle plugin/library versions, repository restrictions, and the reviewed Android `minSdk=30`/`targetSdk=36` and shared modules. It is **read-only**.
- By default the script reports `"result": "incomplete"` when Gradle module lockfiles or a populated Gradle dependency-verification SHA-256 ledger are absent; it does **not** pretend that fixed direct dependency strings alone pin transitive artifacts.
- `--strict` turns missing lockfiles or verification metadata into a hard error. **Do not add `--strict` to PR CI before generating and reviewing real Gradle dependencies and hashes on MacBook.**
- `android/tests/test_native_gradle_policy.py` tests accepted pinned configurations, rejection of `+`/`latest`/`SNAPSHOT`/interpolated versions, wrapper checksum removal, repository restrictions, API floor drift, empty verification metadata, and the strict gate.

Once installed in the real checkout (with the Mac connector active), run:

```bash
uv run --project host --locked --group dev --python 3.13 pytest -q \
  android/tests/test_native_api_matrix_harness.py android/tests/test_native_gradle_policy.py
uv run --project host --locked --group dev --python 3.13 python \
  scripts/audit_native_gradle_policy.py
```

Only after reviewing the actual Gradle graph and producing **real** Gradle lockfiles/metadata from the authorized dependency sources should the strict gate be enabled:

```bash
uv run --project host --locked --group dev --python 3.13 python \
  scripts/audit_native_gradle_policy.py --strict
```

The two new tools and their 26 independent *synthetic* tests were tested in an isolated Python container on 2026-10-12. They have **not** been exercised against MacBook's actual repository, Android device, or Kotlin toolchain in this chat. The static guard returned `incomplete` on a constructed configuration matching the previously observed Gradle baseline; this is a simulated input, not actual current repository evidence.

For CI budget stewardship, run expensive four-emulator ABI/API tests on the high-resource MacBook at milestones or on relevant Native PRs rather than duplicating every feature-branch push and PR. Keep lint/unit/manifest checks cheap and immediate; do not weaken release gates because a provider's free build minutes are limited.

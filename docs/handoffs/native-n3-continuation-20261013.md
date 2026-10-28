# Native N3 continuation checkpoint — 2026-10-13 (AEDT)

This is an independent, reproducible handoff for the **Android MCP / Native MCP Server** workstream. It does not authorize physical Android-device changes or remote/listener privileges.

## Repository state and ownership

- Repository: `grammy-jiang/android-mcp`; canonical default branch is `main` (not `master`).
- Baseline tested from `origin/main`: `7c4ff1e7350b36c89a59b95a9618c471c8906f5b`.
- Original Native N3 [PR #16](https://github.com/grammy-jiang/android-mcp/pull/16) was **already merged**, merge commit `8005334a8cd7471cfcb98ef2b7eb6ab5b096e987`. Later integration and Host changes are also in the baseline.
- This follow-up owns only the independent Mac worktree `/Users/grammy-jiang/Projects/android-mcp-native-n3-resume-20261013`, branch `audit/native-n3-resume-20261013`. No changes were made in the previous Native or Host worktrees, to production Binnacle, or to a physical Android device.
- Its sole Kotlin source change is **test-only**: `LocalPortOwnerTest.repeatedPortContentionKeepsUncertainShutdownFailClosed`, 100 rounds of eight competing reservation attempts, each with injected unverified stop and a verified recovery. No app/runtime behavior was modified.

## Executed local verification (MacBook Apple Silicon)

All checks below were run against the baseline above, then the changed Native JVM, Python and repository hooks were rerun successfully after the test-only addition.

| Gate | Result / evidence |
| --- | --- |
| Native Python Ruff | PASS (`ruff check scripts/smoke-native-emulator.py scripts/smoke-native-foreground-emulator.py android/tests`) |
| Native SDK-free pytest | **86 passed** (`pytest -q android/tests`) |
| `scripts/check-native.sh` | PASS: JDK 17, Gradle protocol/lifecycle/JVM tests, Python↔Kotlin local MCP smoke, offline policy and 86 Python tests |
| Gradle dependency integrity | PASS static preflight: 4 lockfiles, 316 verified components, 540 SHA-256 entries; builds also passed with live strict dependency verification |
| `scripts/check-native-apk.sh` | PASS: API 36 signed debug APK, Android Lint and exact four-permission allowlist; APK SHA-256 `c711073a2e02f6ece30d9cbe2c6a853883ba6907a0c57bea3a1404cafae55b93` |
| Full repo `pre-commit run --all-files` | PASS all applicable hooks: formatting, secrets, workflow lint, Host Ruff, mypy, Bandit, lock validation |
| Kotlin contention / uncertain-stop stress | PASS: new JUnit test, 100 × 8 reservations with fail-closed UNKNOWN and verified release |
| Android API **30**, `emulator-5560` | PASS: N2 local service, Home stops; N3 correctly disabled and user warning displayed |
| Android API **33**, `emulator-5558` | PASS: N2 local service, Home stops; N3 correctly disabled and user warning displayed |
| Android API **34**, `emulator-5556` | PASS: N2 HTTP/Home/restart and full N3 notification-denied, explicit start, foreground, Home, competing mode denied, notification Stop, UI Stop, force-stop flows |
| Android API **36**, `emulator-5554` | PASS: same independent N2 and N3 live-emulator acceptance flows |

Emulator evidence comes from the individually invoked guarded smoke scripts. A separate **single invocation of the aggregate `verify_native_api_matrix.py` runner** was not executed; do not claim that it was. No Android physical-device APK installation took place.

## Release gate not yet satisfied

GitHub-hosted CI is **billing-blocked before jobs start**, not a verified code test failure. See [repository hygiene run 38244435230](https://github.com/grammy-jiang/android-mcp/actions/runs/38244435230) and [Host run 38244435227](https://github.com/grammy-jiang/android-mcp/actions/runs/38244435227), whose annotations state payment/spending-limit blocking. Do not raise paid limits to clear this. Thus there is still no new **executed** Linux x86_64 Android emulator or macOS/Linux hosted CI result for the exact follow-up commit. The Raspberry Pi and sextant have no `java` on PATH, so no Linux ARM64 Native JVM run is claimed.

The N3-07 independent Verification/review pass is also outstanding; the `chatgpt-mcp-engineering` review tool was not exposed in the continuing chat. Existing local tests and a manual inspection do **not** replace an independent security review. Keep these unmet gates visible even though N3 itself was merged earlier.

## Next safe tasks

1. Independent review of the current exact commit, especially port-owner race/failure paths, foreground-service lifecycle, notification-stop behavior, local-only binding and permission boundaries. Close blockers with minimal patches and rerun affected tests.
2. If a verified JDK 17 Linux ARM64 execution environment is provided, run Native JVM/cross-language smoke there. An executed Linux x86_64/emulator matrix remains a separate gate; use non-billed self-hosted capacity if approved, not higher Actions spending limits.
3. Review and merge this **test-only** branch through the project's normal PR controls after independent review. Do not re-merge PR #16 or force-push `main`.
4. Plan caller authentication, Host↔Native pairing, cross-process lease fencing, and real-device acceptance as **subsequent gated stages**. Do not enable remote access, root, Accessibility, device mutation or physical-device installation as part of this checkpoint.

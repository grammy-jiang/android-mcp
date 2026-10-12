# Quality and release gates

Adapted from the **principles** of Binnacle's development, testing and quality-gate policies; this is a separate project with distinct scope and no runtime dependency on Binnacle.

## Python Host (enforced now)

As of 2026-10-12, GitHub Hosted Actions cannot start due billing limits; entries below mentioning CI describe retained workflow definitions, **not evidence of a recent executed check**. The current authoritative Host merge gate is the locked local macOS/Linux ARM64 matrix and package/security suite in [Host merge gates](host-merge-gates.md).

| Gate | Current target | Enforcement |
| --- | --- | --- |
| Python | 3.11, 3.12, 3.13, 3.14 on macOS/Linux ARM64 | Local locked matrix during Hosted Actions billing block |
| Deterministic dependencies | `uv.lock`, `uv lock --check --offline` | pre-commit, doctor, CI |
| Static quality | Ruff check and format, strict mypy | pre-commit, CI |
| Security static scan | Bandit medium-and-higher | pre-commit, CI |
| File hygiene and secrets | pre-commit hooks, Gitleaks, actionlint | pre-commit, CI |
| Unit/contract/failure tests | deterministic pytest + Hypothesis bounded examples | pre-push, CI |
| Branch coverage | critical Host modules >=95%; all others >=90% **per module** | `quality-policy.json` + fail-closed checker |
| Module size | <=500 physical lines (production, scripts, tests) | fail-closed checker |
| Packaging | build sdist and wheel; clean wheel install and CLI smoke | Local check-host-package.sh; CI only when available |
| Dependency CVEs | uv audit --project host --locked; retain scheduled audit definition | Manual local audit while Actions billing blocks jobs |

`quality-policy.json` is the authoritative source of per-module limits. Newly added production modules inherit a 90% floor by default. Critical interfaces (ADB parsing/execution, future auth, privilege broker, mutation policy, device lease) require at least 95%, with explicit additions to the policy when implemented.

The module inventory includes **nested packages** such as `security/`; new security modules cannot hide from the policy. Coverage is measured with `--cov-branch`; the checker independently computes **statement** coverage (`covered_lines / num_statements`) and **true branch** coverage (`covered_branches / num_branches`) from each module's raw counters and enforces the minimum on **both**. Invalid or missing counters fail closed. Branchless modules must still meet statement coverage. It also validates that every production module has evidence and rejects stale critical-module entries. Entry-point-only `__main__.py` and package marker `__init__.py` are explicitly exempt. Coverage does not substitute for realistic failure or concurrency tests.

The quality checker itself is covered with negative tests: missing report, weak module, new uncovered module, too-large file and branch coverage disabled.

## Test expectations for every feature

- Positive / negative / edge cases; permission failures, timeouts, disconnected device states, malformed output.
- Input and output match the versioned JSON Schema. No unwarranted reliance on platform-specific paths.
- Fuzz/property tests for parsers and authorization logic; explicit state-machine or race tests for shared device leases.
- Contract compatibility on Host and Native, including unknown optional capabilities and version changes.
- For high-impact operations, tests must prove fail-closed behavior, correct device selection and a safe stop on ambiguous state.
- Real hardware and network/auth checks must run separately from mocks; document the device/ROM/firmware and test provenance.

## Kotlin / Android quality policy (design, **not yet enforced**)

- Native implementation: Kotlin and Android SDK, Gradle Kotlin DSL, committed Gradle Wrapper and dependency verification/locking. Toolchain versions must be selected and locked in a dedicated validated M2 bootstrap.
- Kotlin formatting/lint: ktlint or detekt with reviewed configuration; Android Lint.
- Unit tests: JUnit + fakes for Android platform boundaries; instrumentation tests for Accessibility, UI actions and lifecycle; emulator matrix plus live dedicated LineageOS tablet gates.
- UI reliability tests: screen orientation, fonts/scale, dialogs, failed capture, lock screen, process eviction, network loss, reboot, authentication state.
- Privileged broker: isolated Android process/IPC, explicit grants, denial-path coverage, no root network listener; full threat modeling and approval gates before implementation.
- Build artifacts: debug APK install test, reproducible release metadata, signed build provenance and no secrets committed.

Do not claim Kotlin CI or emulator coverage until there is buildable Android source and the toolchains are installed in CI.

## Delivery boundaries

Pull requests should show affected tests, actual local exact-SHA results and any executed CI results, contract compatibility and security impacts. Independent review is necessary before enabling arbitrary device mutation, remote access, privilege escalation, bootloader/recovery or payment-related workflows. Shipping a Python wheel is not equivalent to deploying an authenticated MCP endpoint.

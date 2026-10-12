# Independent-methods-style review of Host MCP implementation plan v1

**Reviewer:** ChatGPT, in the same conversation as the plan author.
This is an explicitly identified **self-review and repository audit**,
not a separate independent security reviewer. **Date:** 2026-10-13 AEDT.
**Checked commit:** `ac5e62f929b00cd53fd40403c450bf2ff327f7e2`
on `main`, source `docs/host-mcp-implementation-plan-20261013.md`,
repo quality policy, existing FastMCP server and tests, current Native
loopback implementation, Host/Native coordination draft and 95-family
capability directory.

## Scope and review verdict

**Original Host v1 planning quality: REVISE BEFORE SERIAL EXECUTION.**
Strong coverage ambition and suitable explicit merge markers, but the
v1 plan could cause an unattended single developer to wait at unnecessary
gates, take on overly broad PRs, or declare a disabled capability
complete. It was not detailed enough to execute test-first without
repeated engineering choices.

**v2 result: READY FOR SAFE H0.a IMPLEMENTATION** after this planning
PR merges into `main`. High-impact approval-dependent actions
remain `implemented_disabled` or `plan_only`. This finding is
a design-readiness assessment, not validation of 45 implementations.

## Findings, severity and v2 disposition

| ID | Severity | v1 issue | v2 resolution |
| --- | --- | --- | --- |
| REV-01 | High | Broad multi-domain work packages, e.g. HW1.b diagnostics/package/logcat and HW3.a all emulator lifecycle actions | 45 independent H0.a–H9.c work packages in dependency order |
| REV-02 | High | Long-running build/test/trace operations before persistent job/artifact contract | H2.c and H2.d precede builds, emulators, media and trace jobs |
| REV-03 | High | Only terse test themes; no per-operation error, invalid input, cancellation or leak cases | Companion matrix with >5 explicitly named behavioral tests per atomic package, U01–U08 cross-cutting gates |
| REV-04 | High | Human decisions and external review acting as mid-session execution dependencies | ChatGPT resolves normal choices conservatively; approved safe PRs merge immediately; high-privilege enabling stays disabled, no fake independent review |
| REV-05 | High | The shared calendar's 13:00/18:00 windows could delay one serial Chat | Exact-head green gate triggers immediate main merge; calendar is coordination reminder only |
| REV-06 | Medium | Two developers/worktrees implied by umbrella full-lifecycle roadmap | Host Chat is sole writer for Host worktree, no Codex/Claude agent delegation or simultaneous Host packages; Native unaffected |
| REV-07 | Medium | "Complete coverage" ambiguous for 95 families including dangerous Fastboot/external release | Track runnable vs intentionally denied/plan-only/unavailable/excluded, never count 95 as Tool count |
| REV-08 | Medium | Mac/Pi toolchain versions and permissions vary | Fixed CLI test fixtures and different versions, missing installed SDK/NDK/provider cases |
| REV-09 | Medium | Failure after disconnected USB / restart may falsely retry a write | Durable job state before work; explicit uncertain/partial and replay protection cases |
| REV-10 | Medium | AOSP/Play/HW6 lack qualified external infrastructure/identity | Implement mock/contract and truthful unavailable; no unattended account install, ROM flash or device write |

## Actual observed current-state evidence

- Python Host: exactly three registered FastMCP tools; v1 response
  Schemas; default remote bind restricted to localhost; mutation
  coordinator not enabled in default `create_server`.
- Host base tests and quality gate already cover Python 3.11–3.14 on
  MacBook and Linux ARM64, per-module true branch coverage, strict
  mypy/Ruff/Bandit, package install and CLI Doctor.
- Two Raspberry Pi 5 machines now have Fastboot 34.0.5 and ADB
  34.0.5. MacBook JDK 17 + Android SDK/Gradle and ADB/Fastboot
  37.0.1 are configured; version differences matter.
- Native Kotlin gateway has one local status Tool with a
  user-started foreground-service lifecycle; cross-runtime
  authentication and lease fencing remain draft.
- The 115-item broader catalog consists of 95 Host-associated
  entries and 20 Native-primary entries. Full AOSP and production
  distribution providers are not currently installed/connected.
- The GitHub Actions spending block remains; only **actual local
  Mac/Linux test results** may be used as successful Host gates.

## V2 acceptance criteria for the new chat

- Exactly **45 Hx.y packages** with matching **45 package sections**
  and one explicit `M-Hx.y` merge marker each.
- Every package has **six explicitly numbered T-HxY-01 through
  T-HxY-06 cases** (270 prospective behavioral tests), to implement
  as actual named pytest tests. No import-error-only red phase.
- Each package is serial, test-first, tests actual MCP wire behavior
  where relevant and reports per-host exact-SHA test evidence.
- Each verified non-privileged PR merges to `main` **before**
  starting the next; no permanent Host feature fork.
- Normal engineering decisions made by the single ChatGPT developer;
  missing human approval never turns into simulated or actual
  device privilege. A disabled/plan-only slice may be documented
  and merged independently of its eventual privileged executor.
- No physical tablet is selected by default; Native branch, APK
  and shared contract files are left untouched.
- A new Chat session is **not** a persistent eight-hour automation.
  If tools/session end, a durable checkpoint is the honest outcome.

**Next eligible action:** start H0.a when the v2 planning PR has
merged; do not re-review v1 indefinitely or silently start an
unapproved physical device operation.

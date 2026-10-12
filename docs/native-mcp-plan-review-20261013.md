# Native MCP implementation plan: v1 to v2 review

**Reviewer:** ChatGPT in the same review session as the document author.
This is explicitly a **self-review**, not an independent external
security assessment. **Reviewed:** 2026-10-13 Australia/Sydney.
**Repository main baseline:** `950ff6d6430ad9a71d6d6cb269be0554aa515a21`.

**Review verdict:** **v1 needs refinement; v2 is ready to begin
N0.a safe development**. The review does not approve additional
Android permissions, network exposure, physical-device deployment
or userless control. It also does not mean the 228 future tests pass.

## Findings and dispositions

| ID | Severity | v1 issue | Reviewed v2 treatment |
| --- | --- | --- | --- |
| NR-01 | High | About 20 packages mixed Native OS reads, auth, lifecycle, capture or actions | 38 separately mergeable N0.a–N8.b slices, each with one owner and one main merge receipt |
| NR-02 | High | No explicit test definitions for every slice | Six numbered behavior tests per package, **228 prospective cases**, plus eight cross-cutting gates |
| NR-03 | High | Public Native localhost Tool registration could later expose sensitive functions without caller auth | N0.b denies unauthorized caller/Origin before any sensitive Tool visibility |
| NR-04 | High | MediaProjection and Accessibility consent were underspecified relative to Android 11–16 variations | Dedicated feasibility, denied-by-default contract, consent, process Stop and API30/33/34/36 cases |
| NR-05 | High | Host/Native lease was conflated with existing process-local port-owner | N0.c covers only local lifecycle; N6 handles authenticated identity/lease and durable fencing in a fake/inert model |
| NR-06 | High | Files and screen captures lacked a prerequisite secure storage/retention API | N0.e private artifact handles, bounded size/digest/retention before N3/N4/N5 |
| NR-07 | Medium | Two daily fixed Git merge windows could idle an exclusively serial Chat | Merge exact-head safe PR immediately on real passing gates; shared windows remain communication reminders |
| NR-08 | High | Approval-dependent Android features could stop work during owner's sleep or be silently enabled | Fail-closed/inert/plan-only slices; continue next independent safe unit, no physical grant inferred |
| NR-09 | Medium | JNI/Kotlin/JVM green can be misdescribed as Android runtime validation | Separate actual APK/Lint/permission matrix and disposable API30/33/34/36 emulator acceptance |
| NR-10 | Medium | Risk of long native branch drift against Host main updates and active Native PR #39 | One owned worktree/PR at a time, remote main check, exact-SHA merge/tree verification and no touching PR #39 |
| NR-11 | Medium | Full native coverage incorrectly implies root/bootloader/enterprise administrative powers | N8 documents platform limitations and Host-supervised planning without live privilege executor |

## Sources actually checked in the repository

- Actual Native `LocalMcpGateway.kt` exposes one
  `device_status` with zero sensitive Native permissions or
  device fields, served on `127.0.0.1:38765/mcp`.
- Android APK Manifest contains Internet, FGS, specialUse FGS,
  post-notification permission (no Accessibility/MediaProjection).
  `minSdk=30` and `targetSdk=36` in Gradle configuration.
- `scripts/check-native.sh`, `check-native-apk.sh`,
  `check-native-local-ci.sh` and emulator-only API-matrix
  harness exist, but tests have not been executed against *this
  v2 review's code* by writing the spec alone.
- Native N3 app and its port ownership/FGS lifecycle are already
  in `main`; the security draft
  `docs/host-native-coordination.md` is **not a functioning
  distributed authentication/lease service**.
- `PR #39` is an active Native workstream Draft PR at review
  time; it must be re-checked at the next developer session. This
  review does **not** modify it or its worktree.
- GitHub-hosted Actions are unavailable under user billing limits,
  so real local Native/JVM/APK/AVD evidence is required and must
  be labelled by actual test layer.

## Objective acceptance checks for the new plan

- Exactly 38 unique Nxx package IDs in the roadmap, with one
  corresponding test section and `M-Nxx` receipt each.
- Exactly six uniquely numbered case IDs `T-Nxx-01..06`
  per section, **228 cases** total; all N01–N20 catalog
  capability IDs mapped at least once.
- A single Native Chat performs one package at a time, with
  failing test proof, actual APK/permission gate, relevant
  API30/33/34/36 emulator tests and immediate verified
  `main` merge for non-privilege-enabling safe changes.
- Real hardware, privileged Android APIs and cross-runtime
  mutations remain disabled until genuine external permissions,
  independent security review and scoped owner consent.
- Host `host/**` and other Native worktrees are not
  modified or reset by this planning PR.

**Next eligible development:** N0.a baseline/contract
characterization after this document is merged into `main`,
without waiting for new mid-session routine human decisions.

# Android MCP: Host and Native integration schedule

**Status:** proposed operating policy for both development sessions, 2026-10-13
(Australia/Sydney). This document schedules **integration checkpoints**, not
background execution. No clock-triggered Git push/merge is installed; a
connected, authorized integrator must perform and verify each action.

**Repository:** grammy-jiang/android-mcp. **Only permanent integration
branch:** `main` (the user's "master"). There is no separate `master`,
`develop-host` or `develop-native` target. **Code owners:** independent
Host MCP Chat session and Native MCP Chat session, each the sole writer of
its own branch/worktree. GitHub Actions billing is unavailable and the
user does not want to spend on it.

## 1. Mandatory integration clock

Use Australia/Sydney local time. These are *operating targets while a
development session is active*, not a promise of autonomous work or
forced merges.

| Checkpoint | Host stream | Native stream | Main integration rule |
| --- | --- | --- | --- |
| **09:00 each active development day** | `git fetch origin main`; review upstream diff, clean owned worktree, record exact base/head | Same; review Host/Native interface delta and emulator resources | Each active branch records main ancestor and pending conflicts |
| **13:00 each active development day** | Integrate any independently green Host PR | Integrate any independently green Native PR | First integrator wins; second re-fetches and reruns affected gates before its merge |
| **18:00 each active development day** | Mandatory ready-PR sweep: merge green slices or record a precise blocker | Same | Target: no passing PR waits longer than **one working day** to merge |
| **18:15 after any merge** | Confirm merged SHA, tree equality and post-merge Host smoke as applicable | Confirm Native baseline and its applicable smoke | Other stream fetches new `main` before next feature/contract change |
| **Friday 16:00** | List aged Host branches, stale PRs, partial work and open security gates | Same for Native | Every open branch gets a split/merge/block disposition; no silent accumulated integration backlog |

**Hard age rule:** A normal non-privileged feature branch should produce
one reviewable PR within **one working day**, and be integrated within
**two working days** from branch creation if required gates pass. For
large features, merge neutral scaffolding/tests/contract additions as
separate green slices every **one to two working days**. Do not retain
one long-running feature branch across stages. High-risk features may
take longer to review, but never justify merging unsafe code; keep
blocked feature switches **off**, split audited non-enabling commits,
or checkpoint the blocked branch with exact SHA and reason.

If the integrator/device is offline at a window: do not claim a merge,
do not backdate a check, and do not force a branch to main. Push the
owned feature branch when allowed, retain the unmerged commit and
record `blocked` with dependency/schedule. Merge at the next actual
connected verification opportunity.

## 2. Every work package and PR has an explicit merge point

No vague "merge at the end of the stage". The stream-specific plans
list **Hxx/Nxx**, candidate PR slices and the merge checkpoint
`M-Hxx.a` / `M-Nxx.a`. A slice is complete only when the target
GitHub PR is **MERGED into main**, not merely committed or pushed.

1. **Branch start:** select unique worktree and `feature/host-...` or
   `feature/native-...` from current `origin/main`; record base SHA.
2. **RED → GREEN:** add characterization/negative tests first, then
   smallest implementation, then full relevant checks.
3. **PR creation:** open Draft PR on the *first green self-contained
   slice*, not after an entire stage or many features. Scope preferably
   <=5 owned production files per PR, one externally observable contract
   change and rollback plan. Split larger work rather than hide it.
4. **Gate collection:** run exact-head local tests, capture the binary
   hashes/versions, script commands, exit status, target and log paths.
5. **Merge admission:** check remote main SHA and PR head/base; inspect
   actual file scope. On main movement, reconstruct/merge only in your
   owned branch and rerun affected checks. Shared paths need two-stream
   acknowledgement before integration.
6. **Commit to main:** exact-head squash merge through PR (unless a
   reviewed special merge strategy is required); fetch main; compare
   merged Git tree with the tested integrated tree. No force push,
   no unconditional `reset --hard`, and no mutation of another worktree.
7. **Post-merge:** rerun bounded smoke/full suite on merged `main`
   as appropriate; include merge SHA/status in the PR/handoff; other
   stream fetches main before beginning its next slice.

Branches must not stay open just because the other stream is unfinished:
Host read-only Tool work and Native lifecycle/self-health improvements
may merge independently. A blocked cross-runtime feature must not
create a weeks-long branch in either stream.

## 3. Local no-paid-Actions acceptance, separately per stream

| Gate | Host PR | Native PR | Shared interface PR |
| --- | --- | --- | --- |
| Static/secret/hygiene | `uv run --project host --locked --group dev pre-commit run --all-files` and locked Ruff/mypy/Bandit | Same repository hygiene, Gradle strict dependency metadata and Android Lint | Both |
| Unit + MCP contract | `HOST_PYTHON=3.11/3.12/3.13/3.14 bash scripts/check-host.sh` on MacBook and Linux ARM64 sextant, each at exact SHA | `bash scripts/check-native-local-ci.sh` with JDK 17 and SDK 36 on MacBook; `bash scripts/check-native.sh` on a qualifying second Linux setup if actually available | Host and Native suites, contract golden fixtures and negative cases |
| Build / package | `bash scripts/check-host-package.sh` clean wheel/sdist and CLI Doctor on both platforms | `bash scripts/check-native-apk.sh` verifies APK, signature, Lint and reviewed manifest permissions; snapshot artifact hashes | Compatible Host wheel and Native APK as applicable |
| Emulator acceptance | Synthetic fake-ADB HTTP unit/contract included in Host test gate | `bash scripts/check-native-emulator.sh` or `bash scripts/check-native-local-ci.sh --matrix --api30 ... --api36 ...` **only on pre-verified disposable AVDs**, when feature warrants | Paired/fallback test with identified, consented test environment |
| Hardware and destructive operation | No physical writes in default checks | No physical writes unless user authorizes separate bounded test | Explicit device-owner permission and independent security review |
| GitHub Hosted Actions | `unavailable` due billing, never counted as green | Same | Same |

Do **not** weaken a mandatory gate to meet a clock window. A gate
absent because the machine is offline is `blocked`, not `passed`.
For Native high-impact permissions, independently review the APK
manifest and user-consent flow; test on disposable emulators before
separately authorized real hardware. For permission/mutation/auth/
lease/bootloader/flash changes, independent external security review
and explicit user approval remain prerequisites to enabling code.

## 4. One writer per file and cross-stream interfaces

| Path / asset | Default writer | Other stream may do |
| --- | --- | --- |
| `host/**`, `docs/host-*.md`, Host-only test/scripts | Host session | Read, create review comments, ask Host owner for coordinated changes |
| `android/**`, `docs/native-*.md`, Native-only test/scripts | Native session | Read, create review comments, ask Native owner for coordinated changes |
| `contracts/**`, `docs/security.md`, `docs/host-native-coordination.md`, root AGENTS, common CI/config | One named integration owner per shared PR | Review and ACK, contribute contracts through a separate owned branch only |
| MacBook USB/AVD instances and physical Android tablet | Explicit current test owner | Run tests only after confirming ownership and exact disposable vs physical target |
| `main` | GitHub merged PRs under integration process | Fetch/merge, never direct concurrent uncoordinated pushes |

A shared-contract change follows a **three-PR train** if necessary:
`C0` shared versioned schema/fixtures (with Host+Native agreement);
`H1` Host consumes C0; `N1` Native consumes C0. Prefer additive
v2 + old v1 compatibility rather than a breaking in-place edit.
Do not make one side's PR depend on another side's uncommitted file.
The shared PR may merge only after both applicable suites pass; then
either consumer can merge without waiting for the other's unrelated work.

## 5. Concurrent merge and disconnect protocol

- Before each merge, run `git ls-remote origin refs/heads/main`
  (not just stale `origin/main`). If it differs from the tested
  base, stop; calculate the new integrated source, update the owned
  PR safely and rerun gates. Treat Native and Host updates equally.
- **No concurrent merges:** the first actual GitHub PR merge advances
  main; the other must refetch and verify. This is an optimistic
  exact-SHA main serialization rule, not an imaginary permanent lock.
- If the other stream has uncommitted files, never stash, reset,
  clean, cherry-pick into, or rebase its worktree. An old branch can
  remain as a backup after a clean replacement PR is merged.
- After a long offline spell, read remote state, PR status and local
  job IDs before resuming. Do not assume a background command completed.
- Store handoff per stream, not in a shared actively edited STATUS file:
  exact base/branch/HEAD/main SHA, PR, files changed, test commands,
  environment, results, permissions/device touched, merge outcome and
  unresolved blockers.

## 6. Near-term integration slots (planning targets, not promises)

| Local date (Sydney) | Host target | Native target | Expected main checkpoint |
| --- | --- | --- | --- |
| **Tue 13 Oct 2026** | Merge split plans / Stage H0 target inventory contract when ready | Merge split plans / Stage N0 health and permission-readiness design when ready | Plan PR immediately; no device privilege enabled |
| **Wed–Thu 14–15 Oct** | H0.a CLI detection and failure-schema tests | N0.a local status/permission safety characterization | Each green PR at next 13:00/18:00 window |
| **Fri 16 Oct** | H0.b Host toolchain inventory read Tool or reviewed adapter | N0.b Native baseline/lifecycle/protocol test improvements | Weekly stale-branch audit, each independently merged |
| **Mon–Fri 19–23 Oct** | H1 read-only ADB/Fastboot discovery and diagnostics in 1–2 day slices | N1 permitted device/self-health reads in 1–2 day slices | Daily merges, contract handshake when shared |
| **Following weeks** | Proceed H2–H9 only when stage gates and toolchain support are accepted | Proceed N2–N7 under Android permission/security gates | Daily/weekly cadence persists; no unapproved long-lived fork |

The dates above are **targets for active developer sessions**, not
scheduled automations, promised future results or forced merges. Do
not advance a risky or failed feature just to meet these dates.

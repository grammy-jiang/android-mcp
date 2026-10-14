# Host MCP — Serial completion and merge ledger

**Updated:** 2026-10-14 (Australia/Sydney)
**Repository:** grammy-jiang/android-mcp
**Controlling requirements:** [Host serial v2 roadmap](host-mcp-implementation-plan-20261013.md)
and [270 test cases](host-mcp-serial-test-cases-20261013.md).

This is a durable completion checklist, not a declaration that a class name
constitutes an end-to-end implementation. **[x] means merged and verified
on `main`**, with the explicitly scoped fake/disabled limitations intact.
`[ ]` means not finished, including open PRs. A complete step must have
test-first evidence, mandatory positive/negative/fault tests, exact-SHA
macOS and Linux ARM64 Python 3.11–3.14 quality gates, clean packaging,
security review, GitHub checks, verified merge tree and integration checks.
Never enable real physical-device writes, root, capture, external network
or account-based release actions by treating this checklist as permission.

## Checklist (29/45 merged; 16 not merged)

- [x] **01 H0.a** — Existing tools/list + v1 examples → frozen snapshot/denials
- [x] **02 H0.b** — Fixed executable IDs → version/runnable/unsupported, separate JDK/SDK/ADB/Fastboot
- [x] **03 H0.c** — Safe profile + discovered refs → typed capability state/target lease hint
- [x] **04 H1.a** — No target → bounded named devices, state, transport IDs
- [x] **05 H1.b** — Exact target/state → bounded wait, mDNS/forwarding **inspection**
- [x] **06 H1.c** — Device + selected group → typed fixed `dumpsys`/build/battery/network fields
- [x] **07 H1.d** — Device + package/filter → visible package/details/permissions
- [x] **08 H1.e** — Device + exact filters/time/lines → bounded redacted snapshot
- [x] **09 H1.f** — No target or exact bootloader target → devices and mode **read-only**
- [x] **10 H2.a** — Host directories → valid JDK/SDK/AVD/build-tools/NDK state
- [x] **11 H2.b** — Trusted project handle → safe Gradle wrapper/variants/tasks plan
- [x] **12 H2.c** — Artifact bytes → opaque handle/hash/MIME/size/retention
- [x] **13 H2.d** — Prepared action → stable job ID, transitions/recovery/cancel
- [x] **14 H2.e** — Trusted artifact handle → metadata, signature/ABI/resource verification
- [x] **15 H2.f** — Trusted project + allowlisted build variant → job/report/artifacts
- [x] **16 H3.a** — SDK + AVD name → API/ABI/running/snapshot status
- [x] **17 H3.b** — User-scoped test AVD plan → create/delete only MCP-owned AVD
- [x] **18 H3.c** — MCP-owned AVD handle → start/wait/stop/reconcile
- [x] **19 H3.d** — Disposable AVD + snapshot/test condition → state/result
- [x] **20 H3.e** — Test artifact + verified emulator handle → run/result report
- [x] **21 H3.f** — Local debug APK + verified disposable AVD → install/start/uninstall
- [x] **22 H4.a** — Explicit selected emulator/device + policy → sensitive artifact handle
- [x] **23 H4.b** — Exact target → bounded hierarchy with redaction
- [x] **24 H4.c** — Approved target + cap/duration → job/artifact + stop
- [x] **25 H4.d** — Explicit allowlisted remote source → private Host artifact
- [x] **26 H4.e** — Host artifact + safe remote destination → dry-run or emulator write
- [x] **27 H4.f** — Fixed tap/swipe/key intent → simulator/AVD-only execution or plan
- [x] **28 H5.a** — Exact target + redaction → bounded private report artifact — [merged PR #114](https://github.com/grammy-jiang/android-mcp/pull/114), exact merged tree verified; synthetic-only
- [x] **29 H5.b** — Target + bounded stream lease → cursor, poll, stop — [merged PR #117](https://github.com/grammy-jiang/android-mcp/pull/117), SHA 5ff1dd9; exact merged tree verified
- [ ] **30 H5.c** — Debuggable test target + fixed profile → trace job
- [ ] **31 H5.d** — Debuggable app + supported ABI → bounded profile job
- [ ] **32 H5.e** — Trace/log/symbol handles → bounded report with provenance
- [ ] **33 H6.a** — Fake Native identity + signed challenge → deny-by-default interface
- [ ] **34 H6.b** — Exact target+plan digest+fence → durable state machine
- [ ] **35 H6.c** — APK/artifact/target → signed plan, denial by default
- [ ] **36 H6.d** — Target + endpoint → safe route/pairing plan + policy denial
- [ ] **37 H7.a** — Exact Fastboot target → narrow getvar/version/slot snapshots
- [ ] **38 H7.b** — File hash + device profile → match/mismatch, partition/slot plan
- [ ] **39 H7.c** — Target/image/read-only facts → printable manual runbook
- [ ] **40 H8.a** — Host ABI/OS/RAM/disk/toolchain → eligible/unavailable
- [ ] **41 H8.b** — Approved source checkout+target → safe manifest/build plan
- [ ] **42 H8.c** — Eligible worker/fake job → durable build/test result/provenance
- [ ] **43 H9.a** — Versioned APK/AAB/artifact → offline track-readiness checklist
- [ ] **44 H9.b** — Account connector/status → scoped Play/Firebase read or unavailable
- [ ] **45 H9.c** — Signed artifact + release policy → draft/rollback/stop plan

## Current serial handoff

- **Completed:** H5.b (29/45) merged PR #117 at `5ff1dd9`. Both review
  findings were remediated with red-first regression tests; 2,482 tests
  passed per Python 3.11–3.14 on macOS and Linux ARM64, GitHub checks passed,
  packaging passed, and the merged Git tree exactly matched.
- **Active:** H5.c (30/45) bounded synthetic Perfetto, starting from verified
  H5.b `main`; real tracing remains disabled.
- **Worktree safety:** Host-only `host/**` and Host docs. Do not modify
  concurrent Native Android worktrees, Android source, shared contracts
  or other development sessions.
- **Progression rule:** after verifying a merge, change that one item to
  `[x]`, update counts/receipt, reread all unchecked rows and implement
  the first dependency-ready one without requesting routine approval.
  Inability to run a required gate is `blocked`, not `merged_verified`.
- **Truthful execution:** H4/H5 synthetic receipts are not real Android
  capture/streaming; H6–H9 privilege interfaces remain inert/plan-only
  unless separately authorized and independently validated.

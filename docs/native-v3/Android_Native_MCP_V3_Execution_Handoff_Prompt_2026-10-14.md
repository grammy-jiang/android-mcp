# Android Native MCP V3 — Execution Handoff Prompt

Copy the following into a new dedicated development conversation when the owner authorizes implementation. The accompanying design, implementation plan, case registry, traceability CSV and Git repository are the source records. This prompt does **not** itself authorize physical-device actions, privileged permission bypass, data erase, independent security sign-off or paid services.

---

You are responsible for implementing and genuinely verifying the **Android Native MCP V3 real-function gap closure** in `grammy-jiang/android-mcp`. The historical 38 Native N0.a–N8.b packages are **safe groundwork, NOT a complete product**. Do not repeat the earlier mistake of treating blocked/inert/plan-only branches or merged PRs as feature completion.

Read in full before making changes:

- `Android_Native_MCP_E2E_Architecture_Design_V3_2026-10-14.md`
- `Android_Native_MCP_E2E_Implementation_Plan_V3_2026-10-14.md`
- `Android_Native_MCP_E2E_Acceptance_Matrix_V3_2026-10-14.md`
- `Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json`
- `Android_Native_MCP_V3_Work_Package_Registry_2026-10-14.json`
- `Android_Native_MCP_V3_Legacy_228_Traceability_Template_2026-10-14.csv`
- Repository: `docs/android-host-native-full-lifecycle-design-20261012.md`, `docs/native-mcp-implementation-plan-20261013.md`, `docs/native-mcp-serial-test-cases-20261013.md`, `docs/native-capability-ledger.v1.json`, `docs/host-native-coordination.md`, `AGENTS.md` and `docs/security.md`.

## Mission

Finish real features, not merely source classes: a real MCP client calls the real installed Kotlin Native APK, which executes the permitted Android SDK API with proper OS user consent and authenticated authorization; an independent Android/fixture oracle verifies the success. For each N01–N20, pass all applicable positive, negative, Stop/revocation, concurrency, crash/uncertain-replay and API30/33/34/36 tests. N19 is a separately approved managed-device lab; N20 remains ordinary APK unsupported with a bounded Host fallback. Keep old 228 test IDs and new 192 cases independently traceable. Do not claim old test counts represent executed new E2E cases.

## Mandatory workflow after EACH work package

1. Read latest `origin/main`, active Mac/Host/Pi development and exclusive disposable AVD lease state. Create a new worktree; never edit another writer's files. Preserve Host `host/**` ownership, Native `android/**`, and shared `contracts/**` three-PR C0–Host–Native coordination.
2. Select next dependency-ready `E00.a` through `E15.c` item or a newly created higher-priority `GAP-*`. Implement one real vertical slice, not a mock-only model.
3. Write unit and real Android instrumentation/actual MCP E2E positive, denial, recovery and teardown tests first; prove a meaningful RED. Implement the Native Tool registry/policy/API/OS callback path and prove GREEN using the actual APK on verified API30/33/34/36 QEMU. Use independent OS or fixture proof of the effect.
4. Do not count Host ADB input/install as execution by the Native app. Do not count an Android unit, fake approval, source-level static assertion or generic N2/N3 smoke as feature acceptance.
5. Run locked Kotlin/Host tests, actual AndroidTest, genuine MCP `tools/list` and `tools/call`, artifact/hash checks, Manifest/permission checks, hostile callers, concurrent Hosts, Stop/crash/revoke and per-API E2E. Capture exact Git HEAD/tree, signed APK hash, fixture hash, QEMU IDs, privacy/security result and cleanup.
6. Inspect all requested behavior against N01–N20, original 228 specs, all V3 192 scenarios and newfound platform failure modes. **For every missing positive behavior or missing E2E test, immediately create a required `GAP-Nxx-###` with owner, reproduction, next implementation task, acceptance cases and release-blocking status.** A blocked requirement remains NOT_DONE and cannot vanish from the backlog or be counted as completed.
7. Self-review real code/API/permissions and obtain any genuinely independent security review where required. A developer cannot self-certify independent approval. An absent operator OS consent, approved Android capability or physical test authorization cannot be forged or bypassed.
8. Merge the increment through a focused PR only after its own valid checks; verify the merged tree exactly matches the tested tree and rerun necessary real E2E on main. **An increment may be MERGED while its owner feature is still NOT_DONE.** Update both counters separately.
9. Continue to the next dependency-ready task or GAP without asking for ordinary engineering decisions. If one task is truly externally blocked, record the exact external gate, continue all independent safe work, and leave a durable GitHub checkpoint. Do not promise invisible work when the active tools/conversation end.
10. Stop only when all requested real features meet defined scoped `EMULATOR_FUNCTION_DONE`/approved `PRODUCTION_FUNCTION_DONE` criteria, the true intended ChatGPT MCP client successfully uses them, independent reviews/OS consents are authentic and all required GAPs are closed—or report the remaining blockers as PRODUCT_INCOMPLETE, never as 70/70 means Done.

## Safe starting action

Begin by investigating E00.a–E00.d and E01 AndroidTest infrastructure. Find the first positive Android–MCP behavior not yet callable. Never touch a physical device, Root/ROM, user accounts, or other writers' AVDs without explicit operation-specific approval.

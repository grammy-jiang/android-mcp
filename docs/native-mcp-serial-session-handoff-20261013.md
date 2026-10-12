# Native MCP single-chat development handoff

Use this as the starter for a **separate ChatGPT Native MCP development
conversation**. It is not an automation or a promise of background
progress after the active execution context ends.

## Copy into the new ChatGPT chat

> You are the **sole direct developer, tester, self-reviewer and Git
> integrator** for the **Android Native MCP Server** workstream in
> the private repository `grammy-jiang/android-mcp`.
> `main` is the only permanent integration branch.
>
> Immediately inspect GitHub `main`, existing worktrees,
> Native PRs (especially prior `PR #39`) and any active
> jobs. Connect to **MacBook Pro MCP** for Kotlin/JDK17/SDK36
> work, and optionally sextant/Raspberry Pi MCP for read-only
> independent verification. Do **not** edit another writer's
> worktree or Native PR; create a fresh exclusive branch/worktree.
>
> Read these repository documents directly:
> `AGENTS.md`, `docs/security.md`,
> `docs/native-mcp-implementation-plan-20261013.md`,
> `docs/native-mcp-serial-test-cases-20261013.md`,
> `docs/native-mcp-plan-review-20261013.md`,
> `docs/native-foreground-n3.md`,
> `docs/host-native-coordination.md`,
> `docs/host-native-integration-schedule-20261013.md`.
>
> Start **N0.a immediately**, unless Git shows it was
> already implemented and verified merged; then choose the
> first outstanding safe Nxx. Follow 38 slices **strictly
> serially**, one work package active at any time. For
> each: write its **six numbered failing behavioral tests**,
> implement minimal Native Kotlin/Android code, test actual
> Kotlin SDK Tools list/call schema/results and lifecycle.
> Run `bash scripts/check-native-local-ci.sh` with JDK17
> and SDK36, verifying the APK signature, Android Lint,
> exact manifest permission allowlist and Kotlin/JVM HTTP
> smoke; for permission/FGS/UI features run API30/33/34/36
> emulator acceptance on **preverified disposable AVDs**
> before claiming Android behavior is verified.
>
> Self-review real code and safety consequences honestly.
> Create a focused PR, merge into `main` **immediately
> after its mandatory gates pass**, confirm exact-head main
> and tested source Git-tree equality, then start the next
> package from latest main. No need to wait for fixed
> 13:00/18:00 windows or a sleeping owner's routine
> design/code decisions. Do not delegate implementation
> to Codex/Claude/another parallel worker.
>
> The owner will not be available for several hours.
> **Do not pause to ask routine technical questions.**
> Resolve safe choices conservatively and document them.
> If a dependency/permission is missing, implement truthful
> **disabled, inert or plan-only** contract and associated
> tests; record the blocked enabling feature, then proceed
> to a safe independent slice.
>
> **Do not execute physical Android APK install/uninstall,
> userless Accessibility/MediaProjection, Bootloader/Root/
> flashing/erase, silent package management, external
> unauthenticated listener or production release.**
> These require genuine Android permission, independent
> security review and/or user approval, not merely this
> broad development instruction. Never auto-accept
> Google license agreements or pay for GitHub Actions.
> Do not modify Host `host/**` or force-edit
> shared `contracts/**`; coordinate additive
> cross-runtime changes through separate reviewed PRs.
>
> I expect **real Native development and frequent main
> merges**, not just more planning or status narration.
> Poll jobs to completion, preserve exact test/SHA evidence
> and leave GitHub checkpoint records. If the tools or
> conversation cannot continue, make an honest resumable
> handoff; don't claim invisible background work.

## Starting facts to revalidate

At plan review, the actual Native APK had one status
Tool, N3 opt-in foreground lifecycle, local-only
`127.0.0.1:38765` endpoint and no live
Host/Native distributed lease. Manifest permissions were
Internet, FGS, specialUse FGS and notification permission,
not Accessibility/MediaProjection. The latest Native
PR may advance while this document is being written;
resolve fresh Git refs and own a **new** worktree.

New plan: **38 N0.a–N8.b slices**, **228 prospective
T-Nxx case IDs**, strict test-first serial development and
exact-head main merges. These counts are **work to do**,
not passing Native tests.

# Single-chat Host MCP development handoff (copy into a new ChatGPT chat)

**Purpose:** execute the accepted Host serial implementation plan using
the MacBook Pro MCP, Raspberry Pi MCP and sextant MCP connectors.
This is a **new code-development session**, not an automatic background
job created by this document.

## New ChatGPT conversation starter — copy this whole block

> You are the **single direct developer and integrator** for the Host MCP
> workstream in private GitHub repository `grammy-jiang/android-mcp`.
> The Android **Native MCP workstream is owned by another Chat session**.
>
> **Immediately connect** to MacBook Pro MCP and sextant/Raspberry Pi
> MCP. Read the real repository files:
> `AGENTS.md`,
> `docs/host-mcp-implementation-plan-20261013.md`,
> `docs/host-mcp-serial-test-cases-20261013.md`,
> `docs/host-mcp-plan-review-20261013.md`,
> `docs/host-merge-gates.md`,
> `docs/security.md` and the capability catalog. Inspect current
> `origin/main`, PRs, active worktrees/jobs and any Native changes.
>
> **Start H0.a now** (or the first package without a verified merged
> receipt), from the latest `main` in your **own new Host-only
> worktree**. Implement work packages strictly **serially**, never in
> parallel or via a local Codex/Claude subagent. For each package:
> write its named failing tests, implement minimal safe behavior,
> test positive/negative/boundaries/timeout/privacy and actual FastMCP
> contracts. Run locked Host checks for Python 3.11/3.12/3.13/3.14 on
> **both** MacBook and sextant Linux ARM64 at the same exact commit,
> all quality/security hooks and clean-wheel tests. Open a small PR,
> review your own diff honestly, recheck remote main and PR head,
> merge into `main` immediately when all applicable non-privileged
> gates pass, verify the merged tree and rerun smoke; **then move
> immediately to the next package**. No artificial clock-window wait.
>
> I will be asleep/unavailable. **Do not stop to ask me routine
> design/implementation questions or confirmations.** Make safe,
> conservative backward-compatible choices yourself and record
> their rationale. If a dependency is unavailable, fix it safely
> within scope or implement typed `unavailable` / simulated
> behavior and move to the next independent package.
>
> **Safety policy:** do not execute commands on real Android devices
> that install/uninstall apps, change settings, reboot, flash,
> unlock, wipe, root or operate UI without a separate specifically
> authorized safe test. No arbitrary shell, public unauthenticated
> listener, license auto-acceptance, Google Play publishing or
> purchase. Privileged enabling features require real independent
> review/authorization; implement them as **inert/plan-only**
> contracts with rigorous denial tests rather than waiting for me.
> Do not falsely label self-review as independent. No paid GitHub
> Actions or GitHub spending increase. Never modify/rebase/reset
> Native's worktree `~/Projects/android-mcp-native-setup` or its
> `android/**` files; leave shared contracts untouched unless a
> jointly reviewed additive contract is independently ready.
>
> I expect **real implementation and Git merges, not just another
> plan**. Do not interpret a status request as permission to stop
> the work. Always poll real job IDs to completion, verify exact
> commit SHA and test outcomes, and leave GitHub receipts. When
> tools/context/end of session prevent further work, leave a
> durable exact-SHA PR/handoff showing finished, blocked and next
> work; never claim unseen future/background execution. Continue
> safely for as many serial packages as the active session allows.

## Important execution facts

- The project uses Git branch `main`; a second permanent
  `master` branch must not be created.
- PR #38 merged the initial split workstream plans. The v2 Host
  serial plan should be merged before using this starter; always
  confirm the latest repository state instead of relying on a
  historic SHA in a chat summary.
- No Host feature package in this plan is already complete merely
  because the FastMCP framework-first refactor (366 tests at F0)
  is complete. H0.a is the new plan's entrypoint.
- The owner's sleep does not create a timed reminder or autonomous
  scheduled agent. ChatGPT may work only while the requested
  execution session/tool environment is active.

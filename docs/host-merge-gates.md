# Host MCP pull-request review and merge gates

This checklist is **procedural**, not a claim of server-side branch protection.
As of 2026-10-12, GitHub returns HTTP 403 for branch-protection/ruleset APIs on
this private repository, with an account-plan upgrade message. Local commits
and direct pushes may remain technically possible until repository protections
are available. Never label procedural checks as automatically enforced.

## Small read-only Host changes

1. One Host-owned short-lived branch/worktree from the latest `origin/main`,
   with no changes to another workstream's uncommitted files.
2. Record affected paths, contracts, negative cases, command/test evidence,
   risk, device usage, and exact commit/base SHAs in the PR body.
3. Before merge, inspect `gh pr view <N> --json headRefOid,baseRefOid,mergeable,mergeStateStatus,isDraft,reviewDecision`,
   and `gh pr checks <N> --json name,state,link`. All applicable Host checks,
   security/dependency audits, and repository hygiene checks must be green
   **for the exact head SHA**. A skipped required check is not success.
4. Recheck `origin/main` and any concurrent Native/shared-schema changes.
   Rebase only the Host-owned exclusive branch; repeat gates after changes.
5. Complete the applicable independent code review **before** merge. A
   Copilot `COMMENTED` event by itself does not constitute formal approval.
   Preserve the review outcome and merge SHA in the PR.
6. Prefer squash merge with an expected head SHA; confirm merged tree and
   post-merge CI, and let the other workstream know through GitHub.

## Privileged / transport / identity changes

**Never merge an enabling change solely because tests pass.** Enabling APK
execution, external listeners/authentication, force-stop/recovery, elevated
access, or Host/Native shared leases requires an independent security review
with explicit approval, negative tests, rollback/recovery and hardware evidence.
The production composition must remain read-only until external authenticated
transport and true Native lease fencing have been validated.

## Current CI responsibilities

- `host-ci.yml` tests only Host, shared contracts and relevant quality/CI paths,
  and covers macOS/Linux with Python 3.11–3.14.
- `repository-hygiene.yml` runs on every PR and main commit, including
  Native-only, docs-only and workflow-only changes.
- `host-security-audit.yml` checks dependencies weekly and on manual dispatch;
  Host CI also audits them for relevant PRs.
- Android-specific CI and on-device testing remain Native-owned. Changes to
  shared contracts should trigger both runtimes' relevant test gates.

GitHub plan support for mandatory reviews and protected branches is still a
separate administrative blocker; the above is the fallback until enabled.

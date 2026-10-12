# Host MCP review and merge gates — zero-paid Runner mode

These are procedural gates, not a claim of GitHub branch protection.
As of 2026-10-12, protected-branch/ruleset API access for this private
repository requires a plan upgrade. Do not bypass other writers or imply
that documentation alone enforces merges.

## Current policy (2026-10-12)

The user explicitly declined GitHub Actions spending/plan upgrades.
Hosted Actions jobs are failing to start for an account billing/limit
reason, not failing source tests. Do not treat unstarted jobs as
successful checks; do not require paid Hosted Actions to merge
non-privileged Host changes. Keep workflow definitions as historical
evidence, not as proof that a current job ran.

Authoritative verification for the Host is the locally executed
MacBook and Linux ARM64 Raspberry Pi quality gate on the same exact
Git revision. If either target is unavailable, the merge gate is
blocked. Store check outcomes separately from the execution status.

## Small Host changes: required steps

1. Use a fresh, exclusive Host worktree/branch from origin/main.
   Do not alter uncommitted files in the Native worktree or any other
   workstream, and avoid changing shared contracts without coordination.
2. Add a failing protection test before changing production behavior.
   Preserve the three MCP Tool names, versioned JSON envelopes, explicit
   device selection, typed domain errors and default-denied device mutation.
3. On macOS, run the complete Host quality gate for Python 3.11, 3.12,
   3.13 and 3.14, plus security/format hooks, lock consistency and
   separate clean wheel/sdist installation:

       HOST_PYTHON=3.11 bash scripts/check-host.sh
       HOST_PYTHON=3.12 bash scripts/check-host.sh
       HOST_PYTHON=3.13 bash scripts/check-host.sh
       HOST_PYTHON=3.14 bash scripts/check-host.sh
       uv run --project host --locked --group dev pre-commit run --all-files
       uv run --project host --locked --group dev pre-commit run --hook-stage pre-push --all-files
       bash scripts/check-host-package.sh
       git diff --check

4. On Linux ARM64, use a clean, isolated checkout at the exact same
   branch HEAD and run the four Python full Host gates and separate
   clean-wheel installation. Never run actual Android mutation in this
   automated acceptance suite.
5. Preserve the git SHA, toolchain versions, test counts, outcome,
   command, log path and target environment. Check exact PR head/base,
   changed-file scope, domain contract/negative cases, security findings,
   rollback path and relevant independent review.
6. Recheck origin/main immediately before merge. When concurrent Native
   work advances it, replay only the Host-owned commit onto latest main
   in a new branch, rerun required checks and compare the resulting
   Git source tree with the previously verified code when applicable.
   Never force-push another writer's branch.
7. For an accepted non-privilege-enabling PR only, squash merge using
   an exact expected head SHA, then refetch origin/main and check that
   the merged Git tree is byte-for-byte identical to the tested source
   tree. Repeat applicable post-merge Host smoke/full checks.
   Failed, blocked and not-run tests must not be reported as passed.

## Privileged/security-affecting work

Never merge device mutation, external authenticated/unauthenticated
transport, elevated/root access, recovery/bootloader controls or
cross-runtime Host/Native lease fencing on local tests alone. These
changes require separate explicit approval, independent security review,
authorization and negative tests, rollback plan, appropriate Native
coordination and opt-in real hardware evidence.

No such privileged capability is enabled by the FastMCP 2026-10-12
framework-first Host refactor.

## Workflow configurations retained for future use

The repository still contains host-ci.yml, repository-hygiene.yml and
host-security-audit.yml, including dependency auditing, packaging and
other security checks. Their presence does not establish execution.
The weekly audit may be unavailable while billing prevents GitHub
Actions jobs from starting. Dependency auditing can be run manually;
retain and report its output independently.

If paid or self-hosted GitHub Actions become reliably available,
changing the merge policy back requires a separate user decision.
Android Native owns its own tests and release gates.

See host-fastmcp-final-acceptance-20261012.md for this refactor's
exact HEAD, cross-platform evidence and remaining risks.

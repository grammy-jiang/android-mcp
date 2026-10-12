# Host H1–H3 integration verification (2026-10-12)

**Scope:** Host development machine and hardware-free MCP pipeline. This is not
a claim that Android Native, Root, system-flashing, ChatGPT remote authorization,
or real-tablet integration are working.

## Source and review

- Monorepo: `grammy-jiang/android-mcp`
- Quality foundation: [PR #1](https://github.com/grammy-jiang/android-mcp/pull/1), merged.
- H1/H2/H3: [Draft PR #3](https://github.com/grammy-jiang/android-mcp/pull/3).
- Core SHA at first integration: `4f1463cfe46dac6cca7741c1444c362ed4d14947`.
- H1/H2/H3 review patches were checked by SHA-256 before applying to the
  Q1 baseline. The old offline code was reformatted, mypy-checked and
  reconciled with the current FastMCP tool catalog.

## Verified without an Android device

- MacBook macOS ARM64 and Raspberry Pi Debian 13 ARM64:
  `bash scripts/check-host.sh` includes strict mypy, Ruff, Bandit,
  branch coverage and contract tests.
- GitHub Actions 6/6 matrix:
  [CI run](https://github.com/grammy-jiang/android-mcp/actions/runs/38199209050)
  covers Ubuntu/macOS × Python 3.11/3.13/3.14.
- Actual localhost Streamable HTTP MCP process registered
  `device_status`, `adb_observe`, `adb_develop`.
  A disconnected-device request returned typed errors rather than
  opening a device or silently choosing one.
- Host sdist and wheel built on macOS. A clean-environment install,
  packaging CI policy and additional Linux packaging are separate checks.
- `host/tests/test_host_http_fake_adb.py` exercises a real Host HTTP MCP process
  and a synthetic ADB executable (status, observation, bounded Logcat).
  Attempts to execute instrumentation remain blocked. This is a
  deterministic fake, **not** proof of OEM/ROM behavior.
- Static security policy checker now scans nested source packages, including
  every module in `security/`.

## Findings repaired during integration

1. The development Doctor pinned Python 3.13 accidentally via
   `host/.python-version` even when CI ran Python 3.11/3.14.
   Offline lock checks now use the active interpreter.
2. The Host quality policy originally ignored nested package modules.
   A regression test verifies new nested packages cannot evade coverage.
3. H2's temporary boolean approval/lease callbacks were removed.
   Mutations can only delegate to an injected H3 coordinator; default
   construction leaves it absent.
4. Bounded subprocess termination now targets the entire process group
   even if the launcher exits before its descendants close capture pipes.
5. Older MCP tests were updated to expect the actual three-tool catalog.

## Remaining gates

- Independent security review of signed approvals, staged APK trust,
  SQLite replay protection, audit chain and emergency override.
- A *real* Native pairing identity and arbitrated, fenced Host↔Native lease.
- Actual UI/app operations and screenshot transfer on the dedicated tablet.
- Authenticated external MCP endpoint and ChatGPT tool permission tests.
- Enforce advanced lint/branch coverage/security and clean-install packaging
  in GitHub Actions itself. Present matrix only enforces the original
  lint/format/pytest/doctor steps.
- Hardware-dependent macOS and Linux ADB permissions, reboot and recovery.
- No privileged operations enabled or deployed until the gates above pass.

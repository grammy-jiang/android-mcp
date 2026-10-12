# Host real-hardware acceptance and release sequence (2026-10-12)

## Scope and current evidence

Host development and builds remain on the MacBook Pro. The OnePlus Pad 3 is
temporarily connected through **sextant** (Raspberry Pi 5, Debian 13 ARM64).
This is a temporary *test target*; it is not a remote ADB proxy nor part of
the deployed Host service topology.

Live system verified: OnePlus Pad 3, Android 16 (API 36), LineageOS 23,
ordinary ADB shell UID 2000, SELinux Enforcing, no Root. The MacBook's direct
USB path is separately blocked by macOS USB transport restrictions until the
Mac can approve new accessories.

Evidence already performed with real processes and actual USB-connected hardware:

- MacBook/macOS ARM64 and sextant/Linux ARM64: locked complete Host tests,
  Ruff, mypy strict, Bandit, per-module branch coverage and doctor all pass.
- sextant Host CLI doctor discovers the explicitly authorized USB device.
- An independent localhost Host Streamable HTTP server registers exactly
  three tools: device_status, adb_observe, adb_develop.
- Real FastMCP HTTP client successfully invokes status and seven groups of
  fixed ADB observations (identity, boot, battery, display, storage, SELinux,
  shell_identity). Total 0.41 s for that observed run.
- Actual bounded logcat snapshot (10 lines), with content never logged or
  committed. Tests rejected malformed/unregistered devices and unknown
  probes. A denied instrumentation request returned MUTATION_DISABLED.
- No APK install, shell escape, root escalation, reboot, screen capture or
  device modification was performed.
- A repeatable smoke at the Host release-candidate SHA verifies all eight
  read-only groups, including fixed ABI, security patch, SoC and kernel probes.
- Full Host quality gates enforce per-module branch coverage, Python 3.11,
  3.13 and 3.14 on Ubuntu/macOS, clean wheel installation, vulnerability
  audit and pinned hygiene hooks in CI.
- Independent read-only security review identified four P2 issues in the
  pre-merge candidate: observation schema mismatch, implicit ADB executable
  selection, silent response display truncation, and unsafe dollar-sign
  runner components. The corrected release candidate has regression tests
  for all four.

The above proves **local** Host MCP + Linux USB ADB. It does not prove an
authenticated internet-facing MCP server, any Android Native APK, or any
Host/Native distributed mutation authority.

## Repeatable opt-in test

Build checkout from a reviewed Host branch and run, only on the machine that
is directly connected by USB to the authorized tablet:

    uv run --project host --locked python scripts/smoke_host_live.py --device-id YOUR_SERIAL

To explicitly authorize a bounded logcat read *for this test only*:

    uv run --project host --locked python scripts/smoke_host_live.py --device-id YOUR_SERIAL --logcat-lines 10

The script requires an explicit device ID, starts an ephemeral loopback-only
MCP server, invokes read-only observations and denial tests, outputs only a
compact pass/fail JSON summary, and always terminates its test server. It
never prints or stores device diagnostic contents. No hardware test is run
by default in CI.

## Host merge policy

- Confirm CI's full Python matrix, packaging smoke, pinned hook checks and
  dependency audit are green at the exact merge commit.
- All public Host tools must remain explicit-device and fail-closed. The
  default server must never install APKs or execute instrumentations.
- H3 signed-grant, local lease and audit work may be merged as *disabled*
  prototypes, but the Native joint lease and independent security review
  remain prerequisites for enabling mutations.
- Keep Native APK, internet-facing auth/tunnel and arbitrary device actions
  outside the Host read-only release; build them after Host integration.

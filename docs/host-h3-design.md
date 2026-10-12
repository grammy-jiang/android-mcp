# Host H3 security foundations — review-only integration

**2026-10-12 | State: offline review patch; NOT activated in the real MCP deployment.**

This follows Host H1/H2 and the independent Q1 quality-foundation branch. The
current connected development machines and private GitHub integration were not
available. No real tablet, network tunnel, root, APK installation, or
instrumentation execution occurred during H3 preparation.

## Intent

Make the *future* Host Android device-mutating path auditable and fail-closed,
without allowing an MCP model to supply its own permission flag, signer,
trusted public key, or lease. The public Host catalog remains
`device_status`, `adb_observe`, `adb_develop`. This patch does **not** add a
high-privilege public tool.

## H3 components

| Module | Responsibility |
| --- | --- |
| `security/identity.py` | Canonical SHA-256 binding of device ID, action, complete fixed argv, and staged APK digest |
| `security/approvals.py` | Ed25519 public-key verification of 5-minute-max operator grants; one-time use |
| `security/store.py` | SQLite durable grant replay guard and local Host device lease with incrementing fencing token, time and permission checks |
| `security/audit.py` | Minimal durable audit events in SQLite, hash-chained for accidental change detection |
| `security/artifacts.py` | Private, hash-checked APK staging from approved directories, symlink and size checks |
| `security/coordinator.py` | Binds all gates; missing Native lease bridge or trusted signed-grant inbox means **no mutation** |
| `operations.py` | Optional trusted-construction coordinator injection; default MCP factory leaves it absent |

## Security policy

1. The Host carries only **operator public keys**, configured outside MCP.
   Operator private keys must remain outside this machine and outside any
   shell/file tool available to AI clients. H3 contains **no production grant
   issuer** and **no MCP tool for generating operator approval**.
2. Grants are signed over canonical JSON and bind an exact device, complete
   prevalidated action argv and actual staged APK SHA-256 when applicable.
   TTL is limited to 300 seconds; a used nonce cannot authorize twice.
3. A Host-local lease is persisted with SQLite `BEGIN IMMEDIATE`, random owner
   token, expiry and monotonic fencing number. It coordinates Host processes
   only; **it is not a distributed Host↔Native lease**.
4. A trusted **Native lease bridge is mandatory** before mutations can run.
   Its interface is drafted but no production implementation or pairing
   attestation exists; consequently the deployed Host remains fail-closed.
5. An auditable `begin` must be durable before the runner is called. Any
   execution uncertainty, incomplete audit, or failed lease release results
   in a partial/error outcome. Local process exit alone is not proof of a
   successful instrumentation run or APK install.
6. APK bytes are copied into a 0700 staging directory using an opened source
   descriptor and a SHA-256 digest. Private staged files are 0400. The same
   bytes are checked before execution. This is **not immutable against a
   compromised same-UID host process**, and a pre-execution check cannot close
   every possible inode/path replacement race. Fully privileged production
   installation still needs OS-level staging isolation or fd-based execution.
7. Hash-chained audit records detect corruption. They are **not tamperproof**
   against a system administrator able to rewrite the whole DB. External
   audit anchoring and retention policy are additional release gates.

## Remaining hard gates before enabling real mutation

- Reconcile with the real Q1 Host worktree, FastMCP catalog and pinned project
  dependencies. Add explicit `cryptography` to `host/pyproject.toml`, run
  `uv lock --project host` and verify the diff. No offline lock is provided.
- Run macOS + Linux matrix, strict mypy, Ruff, Bandit, coverage and package
  smoke. The only runtime tests in this patch were executed in Linux Python
  3.13 against a **synthetic H1/H2 API reconstruction**.
- Implement a genuinely trusted local/out-of-band operator grant inbox;
  verify device↔Host pairing and exclusive Native lease with fencing and
  renewals; support crashes and disconnections without ambiguous ownership.
- Review transport authentication, authorization by caller identity, audit
  durability/anchoring, recovery controls, process reconcilation, and
  staging TOCTOU hardening independently before enabling installs/tests.
- Harden the earlier H1 observer's `subprocess.run(capture_output=True)`
  implementation: trimming response text *after* capture does not bound host
  memory if a malicious or malfunctioning ADB device streams huge output.
  Route observations through a bounded subprocess executor before release.
- Run opt-in real tablet hardware acceptance, including Mac/Linux USB
  interruption, failed permissions, `adb shell` escaping, Android test suite
  success markers and an interrupted/partial remote operation.

## Do not overclaim

This patch does not make Android Root, ADB Shell or Fastboot available. It
implements foundations and testable injection points, not a production-ready
approval flow. `HostOperationService` remains safe by default. The future
Native MCP is still a separate endpoint within the same Monorepo.

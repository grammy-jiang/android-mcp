# Host H0.c: fail-closed capability profiles and ephemeral target hints

**Status:** Host-only, non-privilege-enabling capability/status contract.
**Scope:** No Android Native code, shared protocol changes, new device write,
external account connection or actual distributed lease.

## Locally enabled visibility

The default Host FastMCP server continues to expose exactly
`device_status`, `adb_observe`, and `adb_develop`, with unchanged v1
schemas, annotations and default-denied physical mutation. Two explicit
local process options are available:

```bash
uv run --project host --locked android-mcp-host serve --capability-profile safe
uv run --project host --locked android-mcp-host serve --capability-profile diagnostic
```

These opt in to the additional **zero-input**
`host_capability_profile` Tool. The `safe` profile lists only D0 Host
family metadata. The `diagnostic` profile adds D1 families but does
**not** remove explicit device selection, permissions or authorization
checks from the existing diagnostics Tools. Neither profile activates
device mutation or high-risk capability families. The Tool is
`readOnlyHint: false` because local version probing can affect Host
tool state, though no physical Android changes are intended.

The separately approved `--toolchain-inventory` flag is required for
H01 (SDK inventory) to appear *runnable* in a profile. SDK presence
alone without Tool registration results in `not_exposed`, never a
claim of caller authority. Missing, malformed or inconsistent Tool
reports fail closed. No `developer` or wildcard profile exists.
Remote bind remains limited to `127.0.0.1`.

## 95-family ledger

The packaged Host-only `host-family-ledger.v1.json` contains the **95**
A/H/P/F/R/E catalogue IDs exactly once; the 20 N-series IDs are
Native-owned and excluded. Each record contains its catalogue risk,
provider/source, phase, disposition, Host owner, test IDs, verification
state and exact merged revision where implementation is established.
Future planned features have `not_run` and no invented merge SHA.
X5 capabilities are excluded from general model execution. Risk-class
downgrades, missing IDs, duplicate IDs and upgrades to runnable without
reviewed implementation are rejected before profile construction.

`runnable` means an already implemented, locally available and
exposed *D0 observation* only. `requires_target` is not a permission:
the existing Tool still checks the exact authorized online ADB device.
Missing providers such as Google Play remain unavailable even when
local Android SDK tools are installed. A profile is a discovery report,
**not** an authorization engine.

## Temporary ADB transport hints

`TargetHintRegistry` accepts a verified, unique online device serial
and transport ID from the current ADB discovery result, then issues an
opaque non-credential reference with a short expiry (default 30 seconds).
The reference is strictly `observation_only` with `authorization:
none`. It is invalidated by offline, ambiguous, changed transport,
stale observation or timeout. References are in-memory and bounded to
128 live entries with expiration pruning. They are **not** durable
device identities, Host/Native pairing, mutation leases or signed grants.

No target reference has been exposed as an executable physical write
Tool. H1 discovery and H6 paired identity/fencing remain separate,
explicitly gated development packages. Tests use synthetic ADB and
fake localhost HTTP, not an actual physical tablet.

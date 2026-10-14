# E01.e — Disposable Android emulator owner attestation and cleanup hardening

**14 October 2026 — Native V3 engineering increment, not product release.**

The Native/fixture test runner now refuses to touch an Android serial unless
the exact owner-marked disposable AVD is booted as a QEMU process with pinned
API, ABI, process PID and kernel boot UUID **and** a valid locally HMAC-sealed
ownership record. The record is bound to the complete original JSON owner
marker, process creation timestamp (to reject reused PID), actual Android
boot epoch, explicit emulator port, serial and Android API, a random
128-bit owner attestation nonce and a 24-hour expiration.

Local HMAC key is a new, random 256-bit mode-0600 private file outside
Git under the operator's .android/avd test-lab directory. Four actual
previously owned AVDs were safely boot/preflight-verified under OS file
locks before one-time provisioning. The key is not a Host application
pairing credential and cannot authorize Android OS permissions or
produce independent product-release approvals. No physical Android device
was touched.

Each **execution** also gets a new random 128-bit run nonce, passed to
the installed Native APK MCP client harness and independent signed fixture
runner. The four-API E01.f gate binds each pair's same run nonce, exact
signed owner proof digest and emulator kernel boot/process identity, and
requires distinct run nonces and signed owner identities across all four
API versions. Stale or missing proof files, expired proof, changed marker,
recycled PID, changed boot UUID, unsigned data, wrong HMAC key, symlink
owner key or insecure file mode fail closed before APK installation.

ADB forwards are inventoried before and after the real MCP app client
invocation. If the client crashes, fails or leaves an unexpected mapping,
the gate fails; it does **not** execute an unrestricted remove-all command
that could break another developer's live Host work. Exclusive local
OS fcntl leases forbid concurrent operations, and lock/secret files use
mode 0600 with NOFOLLOW, avoiding symlink redirection and content truncation.

## Behavior-first testing

On-disk safety and pure attestation behavior initially failed 13
adversarial expectations on the prior inert/follow-symlink code and then
passed after implementation. Examples: unsigned proof, forged HMAC,
changed owner marker, changed kernel boot, physical serial, lstart changed
but PID unchanged, stale/future signature, missing secret, world-readable
credential, spoofed forward mapping, concurrent same-AVD lock contention
and an ADB transport leak even after a nominal MCP success.

The initial API36 installed APK FastMCP + independent fixture smoke was
re-executed against the existing exclusively owned emulator 5562 with
real on-device AndroidJUnitRunner tests, matching owner proof nonce/SHA
and test execution nonce. The final four-API clean-commit gate must be
executed before closing this engineering increment.

### Still open (not automatically checked)

E01.c user-consent flows and app permissions are being implemented in a
different writer's exclusive worktree. E01.e remains **PARTIAL** until
actual user consent, abort/Stop, process death and lifecycle recovery
cases are joined to this nonce/ownership gate on API30/33/34/36. A new
GAP-N16-002 records this deficiency. A 24-hour expired local proof
requires deliberate re-provisioning under current process ownership;
never silently adopt/recreate a stale emulator identity. No signed
local test-lab HMAC grants production Host permissions.

Existing 20 capability families remain NOT_DONE. An E01.f status-only
instrumentation pass is not a V3 device-control feature positive case.

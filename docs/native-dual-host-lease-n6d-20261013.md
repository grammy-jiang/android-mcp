# N6.d — synthetic two-Host / Native lease contention and uncertainty

**Status:** internal, non-executing Kotlin simulator only. Android
MultiHostLeaseBoundary always returns DENIED; the real production Native MCP
catalog contains device_status only, with no new write or lease Tool.

The simulator receives two synthetic, explicitly allowed Host identities
for one Native installation, boot epoch, app package, action digest and
strict v2 schema. A synchronized acquire grants at most one fake active
owner at a time; a concurrent second Host is BUSY. A repeated request is
REPLAY, and a lower/equal fencing number is STALE. Subsequent higher
fences also reject duplicated request IDs and action digests from a
bounded 64-item synthetic replay ledger. TTL is 100–30,000 ms with
monotonic time. Renew/release requires the same fake Host, request ID,
fence and exact action; wrong Host, expired TTL, out-of-order and
repeat release have distinct denied/expired/already-released codes.

A user Stop or simulated process death records an injected, typed
UNCERTAIN recovery snapshot without claiming the operation completed.
On simulated restart the high-water prevents blind replay, but no
private user document, app or Android action is executed. A changed
Native installation/boot epoch, fake signature rejection, unknown
required schema fields or unsupported future version fails closed.
A backwards clock invalidates the fake instance instead of extending
an expired lease. Even an active fake lease returns
realDeviceMutationAllowed()=false and mutation_executed=false.

N6.c separately provides the owner-locked on-disk private high-water
journal. This N6.d simulator's recovery snapshot includes the bounded 64-entry request/plan replay
ledger so the same ambiguous action is rejected even under a newer fence.
Missing, malformed or oversized recovery ledgers fail closed. An expired
lease cannot be reported as successfully released. The snapshot is **not** a durable
authenticated Host record or a production cross-runtime protocol.
No two real Host services, USB device, physical tablet or ADB mutation
are involved. Actual mutation requires mutually agreed signed
contracts, N6.e denied-by-default capabilities, genuine Android user
consent and independent external security review.

Six T-N6D-01..06 Kotlin tests were RED on the permissive stub, then
GREEN after adding fake contention, lease expiry, uncertainty,
recovery and strict schema checks. Five additional Kotlin regressions cover higher-fence same-plan replay,
clock rollback/changed boot, cross-restart same-plan replay, expired
release and malformed/oversized recovery snapshots. The last two
security cases were observed RED on the initial N6.d code and GREEN
after the state-machine corrections.
Six Native Python source/Manifest gates check no real write dispatch,
only safe provenance and unchanged public one-Tool APK permissions.
Full JDK17/SDK36 Host/Native quality, signing, Lint, dependency
integrity and disposable QEMU API30/33/34/36 baseline regression
are required before merging this inert model.

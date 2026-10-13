# Native N6.e — disabled sensitive mutating Tool profile

**State: inert/disabled.** This is an internal Kotlin test fixture and an
Android boundary that always returns disabled. The real Native MCP Tool
catalog remains exactly `device_status`. No user-supplied header,
`approved=true`, synthetic lease, fake signed challenge or locally injected
`fakeRuntimeConsent=true` enables Android UI, APK installation, system
setting changes or screen capture. Real Host/Native pairing and grants do
not exist, and there is no production action executor.

Private metadata classifies these operations as write/sensitive,
non-idempotent, initially disabled, requiring real Android user consent and
independent security review; UI gesture, install and setting changes are
potentially destructive. Internal metadata is **never** advertised in
`tools/list`, and has no Android SDK side-effect adapter. The small
`AndroidMutationProfileBoundary` in the app always returns DISABLED.

The synthetic model rejects wrong process epoch, unverifiable fake caller,
stale fake signature and missing fake lease. Without even the fake consent
signal, it returns CONSENT_REQUIRED; with all fakes present it still returns
DISABLED. Schema, request IDs and SHA-256-shaped fake action digests are
bounded. Synthetic ambiguous receipts leave a bounded 32-digest ledger;
subsequent matching plan digests return UNCERTAIN even with new request IDs
or after an injected process-recovery snapshot. A full ledger **rejects**
additional simulated ambiguity rather than evicting replay evidence. User
Stop is terminal. All receipts report `mutation_executed=false` and
`automatic_retry=false`; identity, nonce, tokens and action IDs are not
serialized.

This recovered fake ledger is **not** an authenticated durable Android
journal. N6.c provides separate persistent high-water and N6.d the inert
multi-Host lease simulator, neither authorizes a real mutation. Actual
privilege activation still requires genuine Android grants, authenticated
Host pairing, cross-runtime lease, explicit owner consent and independent
security review as a separate enabling change. No Host/shared contract,
Android Manifest permission, new public Tool or real device is changed.

T-N6E-01..06 all initially FAILED as six behavioral Kotlin assertions
against the isolated permissive scaffold (not compile failures), then GREEN
with the unconditional deny implementation. Three extra Kotlin tests
cover malformed recovery, 32-record bounded no-eviction fail-closed and
future schema/oversize/bad IDs. Six Python static/Manifest/Tools gates verify
no production registration or new privileged Android service. Complete
Host/Native JDK17/SDK36, APK/Lint/signing, pre-push and verified four-API
QEMU acceptance are mandatory before any merge.

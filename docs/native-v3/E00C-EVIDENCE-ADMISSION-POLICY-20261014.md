# E00.c — cryptographically bound Native V3 real-Android evidence admission

**Engineering:** source-backed admission rules implemented and tested with
explicitly **test-only** Ed25519 keys. **Product:** PRODUCT_INCOMPLETE.

The production operator must independently provision and pin Ed25519 public
trust roots. No private signing key, automatic reviewer approval, self-signed
product trust root or fabricated Android OS grant is included in this code.

## Per-case admission chain

The v1 receipt binds: exact registered V3 case ID, committed SHA/tree, installed
Native/fixture APK SHA256, owned QEMU serial/API/kernel boot, paired Host
fingerprint/scope/boot identity, genuine Streamable HTTP tools/call request
ID and exact bounded response, Native Android API callback in the installed
package, and a different Android fixture process independently observing
the result after the API callback. Each of nine refusal/recovery dimensions
must provide a bounded digest of independently reported real Android
negative-path evidence. No Android user's private data is accepted by the
test artifact profile.

Each case has two independent signatures: the separately pinned fixture/OS
oracle Ed25519 key signs the canonical complete receipt excluding detached
signatures, while the independently pinned reviewer key signs that exact
receipt SHA256 and explicit **evidence-only** decision. The two public roots,
observer/reviewer roles and originating developer must differ. Without a
locally provisioned correct root, the admission fails closed. Replays,
changed callbacks, wrong Android API, stale boot, missing Host pairing,
ADB-as-executor, synthetic grants, incorrect return hashes, unbounded data,
missing cancellation/Stop/death/retry/race evidence and forged review
decisions are rejected. The four-API combiner requires distinct
API 30/33/34/36 receipts for **the same exact test case**.

Local test fixtures generate ephemeral Ed25519 private keys **in memory only**
to demonstrate behavior-first RED then GREEN and tampering detection.
These unit signatures are not independent reviewers or operational
device witnesses. No local test receipt, and no result produced by passing
caller-supplied trust roots, is counted as an actual independently reviewed
Native product feature.

The result is deliberately categorized as
`CONDITIONAL_ATTESTED_CASE_NOT_PRODUCT_RELEASE`, rather than an unearned
`PASS_REAL_E2E`. The actual production product admission must additionally
verify independently controlled trust-root provisioning, the actual
Android fixture callback/oracle identity, full capability-family test matrix,
signed independent release review and final security profile authorization.
Those prerequisites are release-blocking even after the engineering
admission policy is merged.

## Test and source scope

New tests cover evidence schema/replay, distinct external signature keys,
real-code-path constraints, two-stage time ordering, exact source/APK hash
binding, genuine paired read scope, Android API30/33/34/36 matrix,
nine hashed negative/recovery scenarios, signed fixture observation,
reviewer/collector separation, malformed/disallowed IDs and loss of root.

Run under the locked Host Python 3.13 environment:

~~~bash
uv run --project host --locked --group dev --python 3.13 python \
  -m unittest discover -s tests -p 'test_native_v3_case_admission.py' -v
bash scripts/check-native-local-ci.sh
~~~

The baseline V3 registry stays `NOT_RUN` for all 192 new acceptance
scenarios; current 20 product families remain `NOT_DONE`. The signed
OS evidence gate is not a shortcut around a real Android operation or
external security signoff.

**Release gap:** GAP-N01-004 — provision independently approved out-of-band
oracle/reviewer public roots and actual running Android witness/Host
process integrations, test key rollover/revocation and persistent replay
deduplication, then validate accepted receipts on API30/33/34/36.
This is not completed by compiling this verifier.

Rollback: revert this source-only admission policy, tests and V3
tracking document. No Host/Native production listener or Android
permissions are changed.

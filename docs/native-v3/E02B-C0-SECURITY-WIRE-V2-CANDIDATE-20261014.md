# Native MCP V3 — C0 candidate security wire v2 (E02.b)

**Status:** C0_CANDIDATE_NOT_FROZEN — not a production pairing
protocol and not a live Native MCP feature acceptance result.

The proposed single strict envelope at
`contracts/v2/native-security-envelope.v2.schema.json` uses JSON Schema
2020-12, additive to existing `contracts/device-status.v1.schema.json`.
It does **not** modify the Host device_status Tool or the Native
status-only MCP listener. Source-integrity is pinned by SHA-256 in
`contracts/v2/contract-manifest.json`. Six example messages have a
single explicitly named schema version and shared fields:

| Kind | Payload purpose | This parser authorizes execution? |
| --- | --- | --- |
| `pair_challenge` | Fresh bootstrap nonce, bound public identities | No |
| `pair_proof` | Signature-shaped proof over challenge | No |
| `session_authorization` | Claimed scoped session and TLS peer | No |
| `operation_grant` | Scoped action, exact target, digest and OS consent event reference | No |
| `lease_acquire` | Bounded lease TTL, operation digest, monotonically expected fence | No |
| `lease_receipt` | Held/denied/uncertain outcome; automatic retry is **always false** | No |

Both Python and Kotlin implement strict wire parsing, bounds, type checks,
closed fields, signed-message-shaped metadata, known payload variants,
key fingerprints, installation/boot epoch, expiry and cross-language
fixture roundtrips. Host Python uses reviewed `jsonschema`; Native JVM
uses `kotlinx.serialization.json`, with a separate bounded duplicate
key scanner to prevent inconsistent last-wins parsing between runtimes.
The six golden frames are located under `contracts/v2/fixtures`.

Run independent cross-runtime specification smoke from the repository:

~~~bash
uv run --project host --locked --group dev --python 3.13 python \
  -m unittest discover -s tests -p test_native_v3_contract_v2.py -v
./android/gradlew --project-dir android \
  :native-protocol:test --tests '*NativeSecurityWireV2Test'
~~~

The original 228 historical tests and existing Android API 30/33/34/36
Native status-only MCP are not changed. The new Kotlin code is an
inert parser in `native-protocol`, not a new registered Tool or a
self-issued grant.

## Missing work before the schema may be frozen

- Host runtime writer and Native runtime writer must formally agree on
  the same *signed* wire bytes and version negotiation. Neither has
  activated the new frame in a real Host or Native production session.
  Current Host ownership is independent and must not be overwritten.
- For cryptographic signatures, choose/review an interoperable,
  standardized signed-byte encoding (for example an appropriate
  RFC 8785 implementation or a vetted CBOR/COSE envelope). Simply
  JSON-serializing is **not** cryptographic canonicalization.
- Public key fingerprints must be anchored in a genuine OS/operator
  bootstrap, not supplied by MCP argument or ADB forwarding.
- A signature-shaped field is never accepted as a verified signature,
  and a consent event identifier is never a real Android OS grant.
  Both must be independently checked against a fresh TLS peer, OS
  lifecycle callback and trusted persistent replay/revocation store.
- Requested `scope`, `fence`, `ttl_ms` and `grant_message_id`
  are typed **claims**. A real Native action arbiter must enforce
  durable monotonically increasing leases against concurrent Host
  clients immediately before dispatch, including process-death
  recovery and `UNCERTAIN` acknowledgement outcomes.
- Real Android API 30/33/34/36, Host client and non-model authorization
  E2E evidence, independent security review and the actual intended
  ChatGPT ordinary Chat connector remain outstanding.

This candidate MUST NOT be marked E02.b DONE, N17 DONE or N18 DONE.
A successful parser unit test is neither TLS identity proof nor
a credential that permits sensitive Android device control.

Rollback: remove only the additive `contracts/v2` candidate,
its Kotlin parser, tests and this documentation; no Host production
runtime or Android manifest privileges were changed.

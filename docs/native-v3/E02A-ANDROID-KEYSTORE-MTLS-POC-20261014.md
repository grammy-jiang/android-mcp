# Native V3 E02.a — actual Android Keystore / Host mutual TLS POC

**Date:** 2026-10-14, Sydney. **Result:** positive real-device transport
engineering evidence on one exclusively owned API 36 disposable AVD.
**Product:** PRODUCT_INCOMPLETE. N17 has not passed authenticated Native MCP
Tool enrollment, permission enforcement, revocation, or four-version E2E.

## What actually ran

The independent Host is Python 3.13 / stdlib OpenSSL TLS; Android is a
**separate installed** opt-in AndroidJUnitRunner test APK with a real
Android Framework AndroidKeyStore private key. Neither is a Kotlin JVM fake.
Only the isolated, owner-marked API 36 AVD
android_mcp_native_v3_tls_api36_20261014 / emulator-5570 was changed.
Native production APK and Host source files were not modified.

Two directional transports with independent Host/Android identities:

1. **Android is the mTLS TLS server:** actual AndroidKeyStore EC P256
   private key from Android Framework; JSSE/Conscrypt TLS 1.2 on Android
   loopback; Host stdlib OpenSSL clients connect over explicit ADB forward.
   A correct ephemeral pinned Host certificate is accepted once; anonymous
   and wrong Host identities are each rejected. AndroidJUnitRunner
   independently asserts allowed=1, denied=2, deletes its one-use
   AndroidKeyStore alias, and terminates the TLS socket on test completion.
   A transparent, loopback-only byte-forwarder records bounded TLS records
   in RAM. Both client→Android and Android→client captures contain TLS
   handshake plus encrypted application records but **neither contains
   plaintext nonce request, response or HTTP**. Only SHA256/lengths of
   captured ciphertext are retained in gitignored receipts.
2. **Android is the mTLS TLS client:** two AndroidKeyStore EC P256 one-use
   client keys; app connects by explicit ADB reverse to Host loopback
   TLS server. Android verifies a pinned Host X509 leaf with
   serverAuth and 127.0.0.1 IP SAN, while Host verifies exactly the
   expected Android public client leaf. Two unauthorised client attempts
   (anonymous and wrong identity) are denied and the correct client
   exchanges a nonce-bound response. AndroidJUnitRunner independently
   asserts the observed 1/2 outcome and deletes both key aliases.
   Host private key exists only in a mode-0600 TemporaryDirectory and
   is destroyed after this test.

**Important RED→GREEN engineering finding:** The first AndroidKeyStore
JSSE TLS server test failed with **three of three Host connections denied**,
with wire observation proving a real ClientHello reached Android but no
ServerHello was emitted. It was not a socket/ADB routing issue: an isolated
raw five-byte ADB-forward oracle was independently observed and succeeded.
Android's Conscrypt ECDSA TLS signer required a raw ECDSA signature
key purpose: enabling DIGEST_NONE **in addition to** SHA256/SHA512 on the
test-only AndroidKeyStore P256 KeyGenParameterSpec made the real mutual
TLS server handshake pass. Removing this property is a genuine regression,
not an approved insecure mock grant. A future release review must verify
algorithm/key-type constraints on every supported Android version and
resistance to key misuse.

The POC explicitly negotiates TLS 1.2 with
TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256 for reproducibility. TLS 1.3
interoperability, managed-pinned certificate enrollment, key rotation and
revocation are **future tests**, not claimed by this POC.

## Reproducible local gates

~~~bash
export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
export ANDROID_HOME="$HOME/Library/Android/sdk"
bash scripts/check-native-v3-tls-poc.sh
# Complete repository quality checks plus exact-SHA on-device test:
bash scripts/check-native-local-ci.sh --tls-poc
~~~

The TLS test suite requires a clean committed Git tree, exact signed APK
permissions and dependency-locked AndroidJUnitRunner app, successful local
negative/identity/nonce tests, and two genuine Host/Android mTLS exercises.
It refuses missing/wrong emulator, stale boot epoch, missing APK and
unauthorised runtime; no physical devices or public TCP listeners.
The POC never sends real device/user data over its TLS channel. ADB
forward/reverse are transport only, and are removed after the test.
No paid GitHub Actions or external account approvals were used.

Test fixture implementation:

- android/native-v3-tls-fixture, conditionally included only when
  enableV3TlsPoc is true.
- scripts/run_native_v3_tls_poc.py (Android mTLS server).
- scripts/run_native_v3_tls_client_poc.py (Android mTLS client).
- scripts/native_v3_tls_poc.py (fail-closed admission parser).
- Host private credentials do not appear in source, git, logcat or MCP.
  Android test-only *public* certificate is logged with a random nonce
  for the POC; this is **not authenticated user pairing**.

## Mandatory outstanding GAP tasks

- **GAP-N17-002 OPEN, release blocking:** wire this mTLS substrate into
  the **real installed Native MCP Tool listener** and independent Host MCP
  client. A test-only TLS fixture exchanging POC nonce is **not** an
  authenticated Native MCP Tool response, and cannot close N17.
- **GAP-N17-003 OPEN, release blocking:** all API30/33/34/36 TLS
  variants, TLS 1.3 where supported, AndroidKeyStore signing usability,
  mutual certificate validity, rotation/revocation/replay/cross-process
  death/Stop and uncertain-dispatch recovery.
- **GAP-N17-004 OPEN, release blocking:** operator user-visible pairing
  and secure owner-bound Host public key enrollment; never treat ADB
  forwarding or logcat-public-certificate TOFU as identity proof.
- **GAP-N18-001 OPEN:** real durable Host/Native lease and fencing
  pre-dispatch checks remain absent; do not enable device writes.

The two private TLS test apps are not production Native APK capabilities.
N01–N20 product families remain NOT_DONE; 192 new V3 scenarios and
historical 228 spec test results retain their independently classified
evidence. Post-merge OS oracles and trusted security review remain
mandatory for release.

**Rollback:** revert the strictly opt-in test app, parser/gates,
requirements-gap docs and two POC runners. Production Native Tool/Manifest
and Host runtime are unchanged.

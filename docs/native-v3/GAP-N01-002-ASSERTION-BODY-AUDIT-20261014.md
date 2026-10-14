# GAP-N01-002 — 228 historical cases: assertion-body structural audit

**Date:** 2026-10-14 Australia/Sydney. **Product status:** PRODUCT_INCOMPLETE.

This is an auditable engineering increment, **not** closure of GAP-N01-002.
Original historical test requirements are traced to 257 actual test methods.
Their bodies were parsed rather than inferring coverage from test names:
Python `ast` checks executable assertion statements and expected-error
contexts; Kotlin balanced-code scanning ignores comments and literal strings
and requires a genuine adjacent JUnit annotation. Tautological or missing
assertions are rejected. Every method receives a source-file SHA-256,
method-body SHA-256, explicit assertions/forms and evidence classification.
The machine-readable per-case report is
`v3-legacy-228-assertion-audit.json` and is regenerated/verified by source.

## Measured evidence levels

| Source assertion class | Actual test methods | Meaning |
| --- | ---: | --- |
| Kotlin JVM assertions | 216 | Kotlin JUnit tests, not installed Android APK proof |
| Python source-text assertions | 30 | Checks that source strings/manifest markers exist, not actual OS effects |
| Python mocked harness | 10 | Mock/monkeypatch or fake-client behavior, not real Native device action |
| Other Python unit assertions | 1 | Non-OS Python test assertions |
| **Total** | **257** | **228 distinct historical case IDs covered structurally** |

All 228 historical case IDs have at least one nontrivial structural assertion.
This does **not** establish the assertion is semantically sufficient for its
original requirement. It also does **not** establish that the test ran against
an installed Native MCP app, performed Android Framework work, or triggered an
independently observed effect. Per-case `requirement_semantic_review` remains
`NOT_INDEPENDENTLY_REVIEWED`, and `product_e2e_status` remains
`NOT_VERIFIED_REAL_ANDROID_E2E` for **all 228 historical cases**.

## Eleven historical IDs with only static or mocked assertions

There are 40 Python source-only/mock methods in total; many have an additional
Kotlin JVM test. The following 11 historical case IDs have **no other test
method beyond a static source check or a mocked harness**:

| Original historical ID | Evidence limitation | Linked test selector |
| --- | --- | --- |
| `T-N0A-01` | `MOCKED_HARNESS_ASSERTION` | `test_T_N0A_01_catalog_has_no_hidden_resources` |
| `T-N0A-02` | `MOCKED_HARNESS_ASSERTION` | `test_T_N0A_02_android_v1_exact_fields_no_private_host_data` |
| `T-N0A-03` | `MOCKED_HARNESS_ASSERTION` | `test_T_N0A_03_unknown_tool_denied_by_sdk` |
| `T-N0A-05` | `MOCKED_HARNESS_ASSERTION` | `test_T_N0A_05_foreground_stop_requires_android_and_http_proof` |
| `T-N0A-06` | `SOURCE_STATIC_ASSERTION` | `test_T_N0A_06_mutated_fixture_rejected_without_adb` |
| `T-N4B-01` | `MOCKED_HARNESS_ASSERTION` | `test_T_N4B_01_exact_qemu_api_abi_and_boot_preflight_before_action` |
| `T-N4B-02` | `MOCKED_HARNESS_ASSERTION` | `test_T_N4B_02_physical_or_unverified_serial_rejected_before_input` |
| `T-N4B-03` | `MOCKED_HARNESS_ASSERTION` | `test_T_N4B_03_only_own_visible_button_bounded_tap_swipe_key_sent` |
| `T-N4B-04` | `MOCKED_HARNESS_ASSERTION` | `test_T_N4B_04_changed_rotation_or_window_forbids_blind_replay` |
| `T-N4B-05` | `MOCKED_HARNESS_ASSERTION` | `test_T_N4B_05_input_timeout_reported_uncertain_without_retry` |
| `T-N4B-06` | `MOCKED_HARNESS_ASSERTION` | `test_T_N4B_06_cleanup_only_owned_application_on_preverified_emulator` |

These 11 IDs must receive independent relevant non-mocked tests. Cases
asserting real OS UI/lifecycle behavior require installed APK testing and an
OS oracle, not merely replacing mock assertions with more source checking.
The 216 Kotlin JVM methods themselves are also insufficient for full real
Android V3 product acceptance without their respective on-device tests.

## Deterministic validation commands

```bash
python3 -m unittest discover -s tests -p test_native_v3_legacy_assertion_audit.py -v
python3 -m scripts.native_v3_legacy_assertion_audit --repo . --verify
bash scripts/check-native.sh
```

The mandatory Native local test gate now checks the tracked report against
the actual source files and original 228-case registry. Any deleted test,
changed body/source hash, forged reviewer state, missing source file or
comment-only assertion invalidates it. The report contains no device data,
user credentials, signed approval or user-created access grant.

## Remaining work

- **GAP-N01-002 OPEN:** Review all 228 test bodies *semantically*, inspecting
  positive/negative requirements and their actual assertions individually;
  attach independently verifiable reviewer evidence rather than allowing a
  developer-generated assertion count to self-certify correctness.
- **GAP-N01-005 OPEN:** Replace/augment the 11 cases above with real positive
  and negative behavior tests, and verify relevant Android versions and
  actual independently observed effects where original requirements require.
- Every Native product capability N01–N20 stays NOT_DONE. The 192 new V3
  scenarios do not gain a PASS_REAL_E2E from this exercise.

Rollback: revert this purely offline audit tooling, generated report and
traceability documentation; no production APK or Host privileges changed.

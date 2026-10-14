# E00.b — 228 historical specifications: exact executable method audit

**Status:** SOURCE_AND_UNIT_EXECUTION_TRACED only; **PRODUCT_INCOMPLETE**.

**Date:** 2026-10-14 Australia/Sydney. Repository:
[grammy-jiang/android-mcp](https://github.com/grammy-jiang/android-mcp).

## Actual method inventory

The original 228 historical T-Nxx specs are found in
docs/native-mcp-serial-test-cases-20261013.md and the V3 legacy registry.
The mechanical auditor parses actual method definitions and Kotlin JUnit
annotations rather than comment matches, plan-only classes or guessed names.

- **228/228** historical IDs have an existing executable test method.
- **257 distinct named test methods:** 216 Kotlin JUnit + 41 Python pytest.
  29 supplementary methods cover some IDs at a second unit layer.
- All case IDs have exact source path, line, function name, layer,
  original requirement description, owning V3 work package and capabilities
  in v3-legacy-228-source-attribution.json.
- Missing requirements, duplicate selectors, malformed names, Python comments
  and Kotlin functions without actual JUnit Test annotations fail closed.

## Executed local unit and harness evidence — not Android E2E

MacBook ARM64, JDK 17, locked Gradle, Python 3.13:

    ./android/gradlew --project-dir android :native-protocol:test :native-lifecycle:test :native-mcp-jvm:test
    uv run --project host --locked --group dev --python 3.13 pytest -q android/tests --junitxml=artifacts/native-v3-e00b-python-junit.xml
    python3 scripts/native_v3_legacy_attribution.py --repo . --kotlin-test-results android --python-junit artifacts/native-v3-e00b-python-junit.xml --require-all-unit-results --out artifacts/native-v3-e00b-unit-attribution.json

Actual Gradle and pytest succeeded. The local JUnit/pytest XML contains
**257/257 passing exact method identities** and therefore **228/228 case IDs**
with reported passing local tests. A failed, skipped or missing exact result
never passes the automated per-case gate.

**This is not positive Native MCP E2E.** The reported historical passes do not
prove authenticated Native APK operation, actual Android framework effects,
OS consent, independent observer evidence, failure recovery, Stop behavior,
or per-case API30/33/34/36 acceptance. The old V3 traceability registry
continues to say NOT_RUN_V3 for this reason, and 0/20 capability families
remain independently verifiable as product-complete.

Per-case test-body semantics are not independently reviewed: matching the
historical naming convention is stronger than class existence, but not
sufficient to claim that every requirement was comprehensively asserted.

## Required gaps after this engineering increment

- GAP-N01-002: inspect assertion semantics for every mapped ID, including
  the 29 cases with supplementary cross-layer methods.
- GAP-N16-002: test the relevant historical scenarios against the actual
  Android APK and independently verify OS effects / Stop / recovery.
- The 20 existing GAP-N01-001 through GAP-N20-001 entries remain open:
  Native feature positive paths, scoped authorization, emulator matrix,
  denial/revocation/cancellation and independent release gates.
- Original E01.c and E02–E15 dependencies remain required. No V3 product
  feature or V3 acceptance case status was upgraded by unit XML.

Raw JUnit/pytest XML and executed-method receipts are gitignored under
artifacts/; versioned source map contains no device identity or credentials.

Rollback: revert the offline auditor, V3 evidence documentation and Native
quality script extension; no Android production permissions or Host tools
were changed.

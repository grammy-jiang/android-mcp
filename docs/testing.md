# Test strategy

## Layers

1. **Pure unit tests (Host, current):** ADB parsing, error handling, platform normalization, CLI guards, capability logic; no ADB daemon or Android device required.
2. **Contract tests (current):** JSON Schema fixtures and the FastMCP local in-process client; detect drift of shared data formats and tool lists.
3. **Host-process integration (implemented, hardware-free):** launch the actual Host CLI over localhost Streamable HTTP; exercise device discovery, allowlisted probes, typed Logcat and mutation denial through an executable synthetic ADB in PATH. See `host/tests/test_host_http_fake_adb.py`.
4. **Android JVM tests (implemented in N0):** Kotlin protocol decoder and lease-state fakes, plus Python-to-Kotlin localhost MCP smoke. No Android SDK or emulator needed for the JVM-only checks.
5. **Android APK/emulator (in progress):** N1 builds a foreground-only loopback APK; emulator lifecycle acceptance remains a separate Native gate. Accessibility, screenshots, UI actions, process death and background limits are not established by JVM-only smoke tests.
6. **Real hardware E2E (Host read-only verified, Native future):** Host USB/HTTP observation has passed on sextant/Linux ARM64. Native APK hardware and cross-runtime control remain separate opt-in gates, never implicitly run in CI.
7. **Fault/recovery/performance (future):** disconnect/reconnect, no permissions, device offline, timeout, corrupted state, multi-device, lease expiry, screen-lock, ROM/service restart.

## Gates

```bash
# Smallest evidence during implementation
uv run --project host --locked --group dev pytest host/tests/test_adb_quality.py -q

# Enforced full Host development gate (macOS and Linux)
./scripts/check-host.sh

# Full configured commit and push hooks
uv run --project host --locked --group dev pre-commit run --all-files
uv run --project host --locked --group dev pre-commit run --hook-stage pre-push --all-files
```

Host CI runs macOS + Linux × Python 3.11/3.12/3.13/3.14 tests and validates both per-module statement and true branch coverage in the full Host check. A separate packaging job validates distribution installation; repository hygiene runs on every PR, and a scheduled Host audit checks vulnerability data weekly.

## Coverage integrity

`scripts/check_quality_policy.py` independently enforces statement and true branch counts on every production module, preventing a high combined percent from masking weak branches. `host/.coverage.json` is a generated, ignored artifact. Any new critical module needs a policy classification. A future mutation lane should challenge semantic coverage of the security-sensitive ADB adapter and privilege broker; high coverage alone is not proof of meaningful assertions.

## Hardware separation

No test in `host/tests/` should need a connected tablet, root, fastboot device, internet access or USB permissions. Hardware tests will be opt-in and must explicitly name the target device, avoid destructive actions, and not infer a host↔native identity merely from a shared serial string.

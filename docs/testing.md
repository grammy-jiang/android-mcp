# Test strategy

## Layers

1. **Pure unit tests (Host, current):** ADB parsing, error handling, platform normalization, CLI guards, capability logic; no ADB daemon or Android device required.
2. **Contract tests (current):** JSON Schema fixtures and the FastMCP local in-process client; detect drift of shared data formats and tool lists.
3. **Host-process integration (planned with new commands):** launch localhost Streamable HTTP, inspect actual MCP tool round trips; fake ADB executable in PATH for deterministic outcomes.
4. **Android JVM tests (future):** Kotlin adapters, durable state and privilege-policy fakes, no emulator required.
5. **Android instrumentation/emulator (future):** AccessibilityService, screenshots, UI actions, process death, background limits.
6. **Real hardware E2E (future):** Mac/Linux over USB and native HTTP separately, then coordination. Dedicated tablet required; opt-in and never implicitly run in CI.
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

CI runs macOS + Linux × Python 3.11/3.13/3.14 tests; the separate quality job runs the full branch coverage gate. A separate packaging job validates distribution installation, and a scheduled security job checks vulnerability data.

## Coverage integrity

`scripts/check_quality_policy.py` enforces every production module, preventing an aggregate percent from masking weak files. `host/.coverage.json` is a generated, ignored artifact. Any new critical module needs a policy classification. A future mutation lane should challenge semantic coverage of the security-sensitive ADB adapter and privilege broker; high coverage alone is not proof of meaningful assertions.

## Hardware separation

No test in `host/tests/` should need a connected tablet, root, fastboot device, internet access or USB permissions. Hardware tests will be opt-in and must explicitly name the target device, avoid destructive actions, and not infer a host↔native identity merely from a shared serial string.

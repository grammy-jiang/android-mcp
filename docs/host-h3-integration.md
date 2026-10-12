# H3 integration instructions

This is an offline handoff; the **real** `feature/quality-foundation` working
branch may contain uncommitted work. Never use `reset --hard`, `clean -fd` or
forced checkout to apply it. Do not claim production deployment.

1. Finish and commit the pre-existing Q1 changes on a safe feature branch,
   after reviewing `git status` and `git diff`.
2. Apply the previous H1 patch followed by H2 (or use the combined H1+H2
   patch once). Run the full locked Host quality gate and actual FastMCP
   in-process tests.
3. Apply `android-mcp-host-h3.patch` with `git apply --check`, then `git apply`.
   Review *all* code, including the cryptography dependency addition and the
   policy floor for H3 security modules. The patch is built against a faithful
   **synthetic** H2 file snapshot, not real Git repository history.
4. Run `uv lock --project host` intentionally to generate the cryptography
   lock change and re-run `uv sync --project host --locked --group dev`.
5. Run `python3 scripts/dev.py check`, both Git hook stages, mypy strict,
   Bandit, Ruff, per-module branch coverage and real FastMCP tool discovery.
6. Independently test Linux and macOS and the clean-wheel installation; only
   then push the feature branch and verify exact-SHA GitHub CI.
7. Do **not** install a trusted operator inbox or Native lease bridge during
   this integration. Live mutations remain blocked until external security
   review, real device testing and a separate explicit release gate.

## Offline evidence

The test workspace includes the H1/H2 code snapshot, the H3 security sources,
H3-only tests, H2 integration tests and a minimal *synthetic* `adb.py` stub.
All H3 deliverable files are separately included in the review bundle;
**never copy the synthetic ADB stub into the real Host project**.

The attached output shows the specific modules and passing tests; no actual
FastMCP `Client`, macOS, Raspberry Pi, Android tablet or GitHub CI was invoked.

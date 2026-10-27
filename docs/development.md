# Developer workflow (canonical)

This document owns bootstrap, local checks and collaboration conventions. `AGENTS.md` is only a brief entrypoint. Quality policy is specified in [quality.md](quality.md) and [testing.md](testing.md).

## Host toolchain

- macOS or Linux (including ARM64 Raspberry Pi); Python 3.11–3.14, preferred development interpreter Python 3.13 from `host/.python-version`.
- `uv` >=0.13.4,<0.14 (GitHub CI uses `uv` 0.13.4; `host/uv.lock` locks Python dependencies).
- Git, and optional official Android Platform Tools. ADB and an attached tablet are **not** needed to run any current tests.
- Native/Kotlin development will require a tested JDK (minimum 17 for AGP 9.4), Android SDK/Gradle plugin and signed debug APK workflow; **not bootstrapped by this Host script yet**.

### Bootstrap a new checkout or worktree

```bash
python3 scripts/dev.py bootstrap
python3 scripts/dev.py doctor --require-hooks
```

The bootstrap command synchronizes the **locked** Host environment and installs both pre-commit and pre-push hooks. It does not install OS-level packages, configure a network listener, set Android permissions or deploy either MCP service.

For CI and agent tooling:

```bash
python3 scripts/dev.py doctor --json
```

Doctor checks the Git root, uv availability, offline lock consistency and hook status. Missing hooks are reported but not required unless `--require-hooks` is passed; dirty worktrees generate a warning, not an error. ADB, Java and SDK are informational only during Host development. `android-mcp-host doctor` has a different purpose: runtime ADB/device diagnostics.

### Normal development loop

```bash
uv run --project host --locked --group dev pytest -q host/tests/test_adb.py
python3 scripts/dev.py check
uv run --project host --locked --group dev pre-commit run --all-files
uv run --project host --locked --group dev pre-commit run --hook-stage pre-push --all-files
```

- Run focused tests during a small change. Run the comprehensive quality suite before integrating.
- **Do not change dependencies through a test run.** Deliberate upgrades require `uv lock --project host`, review the diff and commit the updated `host/uv.lock`.
- Use `git worktree add` for independent contributors/agents; separate feature branches and run bootstrap per worktree. Never copy `.venv` between checkouts.
- Before every commit, pull, rebase or integration, re-check Git status and ownership. Do not reset, stash, clean or overwrite another task's uncommitted work.
- Keep Android Native and Host tasks independent where possible; contracts or shared quality policy updates coordinate across workstreams.
- Python type checks and tests must run on macOS **and** Linux, not just a mocked OS platform string.

### Development is not deployment

The current Host MCP has three localhost-only tools: device_status, adb_observe, and adb_develop. The latter supports bounded read-only diagnostics and non-mutating action previews. Actual APK installation/instrumentation remains disabled in the default server. The real USB Android 16 read-only Host HTTP path is verified on Linux ARM64 (see [Host live acceptance](host-live-acceptance.md)), not authenticated public deployment. Do not expose it publicly or enable device mutation without independent auth/transport, Native lease fencing, and explicit release gates.

Release policy is documented in [quality.md](quality.md); no PyPI / APK publishing job exists at this stage.

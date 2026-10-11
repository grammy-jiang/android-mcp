# Engineering guidance for Android MCP

Read `README.md`, `docs/architecture.md`, `docs/compatibility.md`, `docs/security.md`, and `docs/roadmap.md` before substantial changes.

## Non-negotiable boundaries
- This is an independent project. Do not modify, import, or deploy Binnacle.
- Monorepo does not mean one executable: Host (Python on macOS/Linux) and Android (Kotlin APK) deploy independently.
- Build, lint, and test should work without a connected Android device, ADB installation, Android SDK, credentials, network tunnel, or root.
- Keep shared contracts neutral: no Python/Kotlin class names in wire formats.
- Require explicit device identifiers before any future mutating operation.
- No default arbitrary `adb shell`, root shell, exposed TCP debugging port, remote unauthenticated MCP endpoint, bypass of app security checks, or automated payments.
- Treat screenshots, UI trees, addresses, tokens, device IDs and app data as sensitive; no logs containing secrets.
- Changes requiring elevated privileges or recovery procedures must be independently gated, reversible when possible, and auditable.

## Development commands
```bash
uv sync --project host --locked --group dev
./scripts/check-host.sh
uv run --project host --locked android-mcp-host doctor
```

Use targeted tests during implementation; run the full host suite at merge/release gates. Do not assume a macOS success implies Linux success or vice versa.

## Workstream contracts
- Shared contracts: `contracts/`, cross-runtime schema versions, fixture examples.
- Host: `host/`, subprocess-safe ADB and Fastboot providers, macOS/Linux portability.
- Native: `android/` (later), Android app/service lifecycle and permission broker.
- Business adapters: isolated from device control; no Taobao/Goofish/JD API reverse engineering.

For handoffs, state inputs, outputs, affected tests, device requirements and security implications. Keep per-workstream files independent when parallel development is useful.

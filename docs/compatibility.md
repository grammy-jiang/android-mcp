# macOS + Linux compatibility contract

## Supported Host targets

| Target | Initial test baseline | Runtime expectation |
| --- | --- | --- |
| macOS ARM64 | macOS 27.0.1, Python 3.14.8, ADB 37.0.1 | Homebrew or official Platform Tools |
| Linux ARM64 | Debian 13, Python 3.13.5 | apt-provided or official Platform Tools; may initially have no ADB |
| CI macOS / Linux | Python 3.11, 3.13, 3.14 | mocked ADB; no Android hardware required |

These are observed baseline machines for the first implementation; not a vendor support matrix for all Linux distributions or future macOS releases.

## Portable Host design rules

1. Python >=3.11,<3.15; do not depend on a platform-specific Python binary path.
2. Find `adb` with `shutil.which` or an explicitly configured executable. Do not assume `/opt/homebrew/bin/adb`, `/usr/bin/adb`, or an Android SDK directory.
3. Execute an **argument vector** with `subprocess.run(..., shell=False, timeout=...)`. Never construct a shell command by concatenating a device serial, path, or user text.
4. Use `pathlib`, UTF-8 text decoding with replacement, numeric timeouts, and normalized error codes.
5. Implement process/service management behind separate platform adapters when introduced: launchd on macOS, systemd user services on Linux. Do not inject systemd commands into macOS code.
6. USB permission troubleshooting differs: macOS may require device trust/USB authorization; Linux may need udev rules and group permissions. Detect and report; do not automatically edit host policy.
7. `adb devices -l` can show zero, unauthorized, offline, recovery or multiple devices. Treat `device` state as an ADB connection, **not** proof that Android finished booting.
8. Explicitly select a serial (`adb -s <serial>`) for future per-device operations. Consider future transport-ID handling without guessing a stable ID across USB/network/reboot.
9. ADB may launch its own daemon upon `devices` inspection; document this behavior. Never automatically enable Wi-Fi ADB or open port 5555.
10. CI tests must run with a fake ADB executor and no device; only separately gated E2E jobs require a real tablet.

## Initial developer commands

```bash
uv sync --project host --locked --group dev
uv run --project host --locked android-mcp-host doctor
./scripts/check-host.sh
```

The `doctor` command should remain successful when ADB is missing or no device is attached; inspect the JSON `adb.error` and `devices` fields for that condition.

## Future actual hardware gates

- Same read-only status output on Mac ARM64 and Linux ARM64 with the **same tablet**.
- Simulated missing executable, non-zero exit, timeout, unauthorized, offline and more-than-one-device.
- Typed APK install/logcat commands and interruption/timeout handling (not part of current scaffold).
- USB disconnect/reconnect, root/non-root, device reboot/fastboot mode.
- Clean startup after process/service restart on both supported OSes.

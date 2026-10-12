#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

# Hardcoded disposable AVD serial for isolated CI. Both Python scripts further
# verify the exact serial and ro.kernel.qemu=1 before ANY device mutation.
serial="emulator-5554"
apk="android/app/build/outputs/apk/debug/app-debug.apk"
test -s "$apk"

uv run --project host --locked --group dev --python 3.13 python \
    scripts/smoke-native-emulator.py --serial "$serial" --apk "$apk"
uv run --project host --locked --group dev --python 3.13 python \
    scripts/smoke-native-foreground-emulator.py --serial "$serial" --apk "$apk"

echo "Both ephemeral Android Native MCP modes passed real emulator acceptance."

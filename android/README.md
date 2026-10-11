# Android native runtime — reserved module

The Android runtime is intentionally **not implemented** in the initial host-focused scaffold. No Gradle wrapper or APK is shipped yet.

Planned app architecture:

1. Kotlin foreground service / MCP endpoint with an explicitly authenticated remote exposure path.
2. Android AccessibilityService + UI tree, gestures, text input and screenshots (subject to system/user grants).
3. A separately protected local privilege broker for optional root/system operations. Root is **not** a prerequisite to ordinary UI control.
4. A durable queue and per-device control lease that can coordinate with the external Host ADB runtime.
5. Plugin-like application adapters (shopping **later**), never hardcoded into the device core.

The native MCP endpoint must remain functional when the desktop host, ADB cable, or Binnacle is unavailable. Host ADB retains recovery responsibilities for cases where Android or its MCP service cannot boot.

See `../docs/architecture.md`, `../docs/security.md`, and `../docs/roadmap.md` before adding Gradle or privileged code.

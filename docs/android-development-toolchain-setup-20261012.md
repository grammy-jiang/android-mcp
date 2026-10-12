# Android MCP workstation toolchains — verified setup

**Checked:** 2026-10-12 (Australia/Sydney).
**Scope:** MacBook Pro (macOS ARM64), Raspberry Pi 5 `raspberrypi`, and
Raspberry Pi 5 `sextant`, for Stage 0 Host/Native MCP development.

This records real toolchain configuration and read-only command validation;
it is **not** a Flash/Bootloader permission or a claim of real Android device
compatibility. No `fastboot devices/getvar/flash/erase/unlock/reboot`,
APK install, ADB device mutation or physical-device command was executed.

## Verified host versions

| Host | Java / SDK | ADB | Fastboot | Evidence |
| --- | --- | --- | --- | --- |
| MacBook (arm64) | OpenJDK 17.0.20.1; Android SDK Build Tools 36.0.0; Gradle wrapper 9.6.0; Emulator 37.2.12.0 | 37.0.1 | 37.0.1 (already installed) | Java, Javac, Gradle version, SDK-local sdkmanager/apkanalyzer/apksigner, version/help succeeded in a new zsh login shell |
| raspberrypi (Debian 13 arm64) | No full SDK/JDK provisioning in this task | 34.0.5 | newly installed 34.0.5 | Exact Debian dpkg package status and binary version passed |
| sextant (Debian 13 arm64) | No full SDK/JDK provisioning in this task | 34.0.5 | newly installed 34.0.5 | Exact Debian dpkg package status and binary version passed |

### MacBook: JDK and SDK configuration

The existing Homebrew OpenJDK 17 was reused (not reinstalled).
`brew link --force openjdk@17` linked Java/Javac into the
Homebrew prefix without replacing another JDK.
The original `/usr/bin/java` macOS shim and
`/usr/libexec/java_home -v 17` now both discover the registered JDK
under `/Library/Java/JavaVirtualMachines/openjdk-17.jdk`.

The following persistent configuration was added as a guarded, exactly-once
block to the user's existing `~/.zprofile` and `~/.zshrc`:

- `JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`.
- `ANDROID_HOME=$HOME/Library/Android/sdk` and matching
  `ANDROID_SDK_ROOT`.
- SDK-local `cmdline-tools/latest/bin`, `build-tools/36.0.0`
  and `emulator` added to PATH if present, with duplicate-path
  detection. **SDK platform-tools were not prepended**, preserving the Mac's
  installed Homebrew ADB/Fastboot 37.0.1 binaries.

Original shell files were backed up in a user-private directory:
`~/.config/android-mcp/environment-backups/20261012/`.

This also fixed an SDK duplication issue: the Homebrew `apkanalyzer`
wrapper could not find locally installed Build Tools, whereas the
SDK-local `apkanalyzer` launches correctly with the JDK.

New login and interactive zsh sessions passed Java/Javac/SDK tool
checks. The existing Gradle wrapper ran `--version --offline`
under JDK 17 without downloading a distribution. This proves toolchain
resolution, **not** an APK or Gradle build. The macOS
`launchctl setenv` attempt failed with error 150 due to
System Integrity Protection. SIP was not disabled or bypassed.
An MCP service launched without a login shell should either use vetted
absolute JDK/SDK paths or set its own service-specific environment;
do not claim an already-running GUI agent inherited `JAVA_HOME`.

For a terminal verification:

```bash
java -version
javac -version
/usr/libexec/java_home -v 17
sdkmanager --version
apkanalyzer --help
apksigner --version
fastboot --version
```

### Raspberry Pi 5: minimal Debian Fastboot installation

The **Debian 13 trixie arm64** official `fastboot` package
`1:34.0.5-12` was installed on both Pi machines with:

```bash
sudo env DEBIAN_FRONTEND=noninteractive apt-get install \
  --yes --no-install-recommends --no-upgrade fastboot
```

APT preview and execution both reported only two new packages:
`fastboot` and `android-libsparse`.
There were **zero upgrades, removals or other installs**. Existing
`adb` (34.0.5) and `android-udev-rules` were retained.
Each host's `fastboot --version` succeeded; worktrees were untouched.

No USB/bootloader behavior was exercised, so actual fastboot-mode hardware
permissions/compatibility remain to be checked on an explicitly designated
test target and only for safe discovery before any device maintenance.

## Caveats / next development stage

- MacBook and Pi versions differ (37.0.1 versus 34.0.5); the eventual
  MCP capability inventory must query supported CLI features separately.
- Tool installation does **not** mean that device flashing, unlocking,
  arbitrary shell execution or Android root operations are authorized.
- User's other worktrees, installed ADB binaries and existing Native
  app code were not modified.
- For a full Android APK build, signed APK test and emulator acceptance,
  use the repository's independent Native quality/hardware gates.
- The four Raspberry Pi 4 nodes mentioned as possible future cluster
  members were not accessed or configured in this task.

Official docs: [Android JDK configuration](https://developer.android.com/build/jdks),
[Android SDK Manager](https://developer.android.com/tools/sdkmanager) and
[Debian 13 Fastboot arm64 package](https://packages.debian.org/trixie/fastboot).

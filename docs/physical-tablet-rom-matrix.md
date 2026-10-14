# Physical-tablet Android ROM compatibility and acceptance matrix

**Verified / researched:** 2026-10-14 (Australia/Sydney). This is the device-specific test plan for the user's existing tablets, not a catalogue of interesting Android distributions. For general emulator coverage, see [testing](testing.md).

## Rules for interpreting this matrix

- **Observed** = read from a connected tablet with explicitly selected ADB target.
- **Device-specific, official** = firmware/ROM vendor names this model or codename on its official support page. This does **not** imply that we have installed or tested it.
- **Community** = an independently published device-specific build, without manufacturer or upstream ROM-project support. Source code, build hashes, maintainer history, recovery evidence and known issues still require review.
- **Conditional GSI** = a generic image, **not** proven to work on this specific tablet. Treble support alone is insufficient to claim practical compatibility.
- A build for a physical tablet cannot be used as an Android Emulator / AVD system image merely because both are ARM64. Physical boot/vendor partition layouts and drivers are device-specific.
- Always match the **exact model, device codename, source build and required firmware** before considering ROM operations. Do not equate OnePlus Pad 1 (`aries`), Pad 2 (`caihong`), Pad 3 (`erhai`), Xiaomi Pad 6 (`pipa`) or Pad 6 Pro (`liuqin`).
- **No ROM flashing, bootloader unlocking, reboot, factory reset, data wipe, ADB-over-network enablement or replacement of an existing installation is authorized by this document.** Any such activity is a separate reviewed/approved maintenance operation. Ordinary read-only observations may run on an explicitly selected connected device.

## Three owned tablets and selected test targets

| Hardware | Identity confidence / current evidence | Primary Android MCP runtime test | Additional candidate ROM | Acceptance status |
| --- | --- | --- | --- | --- |
| **OnePlus Pad 3** | **Observed on sextant**: model `OPD2415`; device property `OP6190L1`; LineageOS codename `erhai`; ARM64; Android 16/API 36; `ro.lineage.version=23.0-20260101-NIGHTLY-erhai`; Treble enabled; SELinux status documented by earlier live acceptance. Boot verified state reports `orange`; not proof of root. | **Existing LineageOS 23.0/Android 16** (preserve). Test directly through sextant USB, then Native/Host acceptance with explicit device selection and grants. | **LineageOS 23.2** (official device instructions) or **crDroid 12/13** (official `erhai` builds, Android 16/17), only as *future separate ROM test runs*; **OxygenOS 16** optional OEM reference, not current installation. | ADB identity read confirmed; **no ROM replacement**, not yet a claim that every Native MCP operation passes. |
| **OnePlus Pad (first generation, not Pad Pro/Pad 2)** | User-owned, **not connected or inspected this session**. Expected global model `OPD2203`, hardware codename `aries`. Exact model/ROM must be verified with its own ADB session. | **The tablet's existing installed OS**, to be inventoried before choosing a change. OnePlus lists the OnePlus Pad for **OxygenOS 16**. | **No verified official LineageOS or crDroid device-specific `aries` build** found as of this review. A third-party ARM64 GSI is *investigation only*, contingent on exact model, bootloader/Treble/partition checks, published device-specific boot report and recovery procedure. | Hardware inventory pending; no custom image is approved for flash. |
| **Xiaomi Pad 6 Pro** | User previously identified this device as `liuqin`. **Not connected or inspected this session**. Expected regional model `23046RP50C`. Historically used Paranoid Android Uvite/Android 14; **do not assume that remains its installed OS**. | **Current installed ROM as found by ADB**. For future reproducible custom-ROM tests, prioritize the existing **Paranoid Android `liuqin` build family** once version, recovery and image provenance are reverified. | **Paranoid Android Uvite/Vauxite** (unofficial `liuqin` builds), **LineageOS 23.2** (unofficial Android 16), **PixelOS 17** (unofficial Android 17 beta). **HyperOS 3** is an OEM firmware/rollback reference, not a preferred replacement. | Model and current ROM inventory pending; unofficial candidates require review and controlled recovery before testing. |

**Pitfall:** The /e/OS device page for `erhai` currently explicitly lists **OPD2413 only**, not the physically observed **OPD2415**. The common codename alone does **not** make that /e/OS build eligible: <https://doc.e.foundation/devices/erhai/>

**Pitfall:** The official crDroid `pipa` image is for the **Xiaomi Pad 6**, not the **Pad 6 Pro (`liuqin`)**. It must never be used for this Xiaomi tablet. Likewise, an unofficial LineageOS build for `liuqin` is not official LineageOS device support.

## Provenance: device-specific reference points

1. OnePlus Pad 3 official LineageOS install/upgrade instructions: <https://wiki.lineageos.org/devices/erhai/install/variant2/> (the wiki was advertising **23.2** at review time).
2. OnePlus Pad 3 official crDroid device list: <https://crdroid.net/downloads> (search `erhai`; crDroid 12/Android 16 and crDroid 13/Android 17).
3. OnePlus OxygenOS 16 official compatible devices: <https://www.oneplus.com/au/launch/oxygenos16> (both the original OnePlus Pad and Pad 3 listed; staged rollout varies).
4. OnePlus Pad (2023) `OPD2203` specification: <https://service.oneplus.com/content/dam/support/user-manuals/in/OP_Aries_QSG_IN_V1.0_230412.pdf>
5. crDroid official device list: <https://crdroid.net/downloads> (`aries` and `liuqin` not listed at review time; `pipa` is a **different** Xiaomi model).
6. Paranoid Android unofficial `liuqin` image archive: <https://sourceforge.net/projects/paranoid-android/files/Xiaomi-Pad-6-Pro/> (Uvite/Vauxite releases). The associated AOSPA device-tree work: <https://github.com/Xiaomi-SM8475/android_device_xiaomi_liuqin>
7. Unofficial LineageOS 23.2 for `liuqin`, including claimed retail-hardware boot evidence and caveats: <https://github.com/AlanHuang99/liuqin-lineageos-23.2>
8. Unofficial PixelOS 17 **beta** for `liuqin`: <https://sourceforge.net/projects/pixelos-liuqin/files/PixelOS-17/>
9. Xiaomi Pad 6 Pro stock firmware catalogue: <https://mirom.ezbox.idv.tw/en/phone/liuqin/> . This is a **third-party index linking stock Xiaomi images**, not a substitute for firmware/region validation.
10. Google official GSI caveats/requirements: <https://developer.android.com/topic/generic-system-image> . Device-specific boot and hardware support are **not** guaranteed.

Review the live upstream pages and exact device identity again before **any** upgrade or flash. The research above establishes build candidates, not image integrity, safe installation or performance.

## Non-destructive discovery and release gates

### P0 — existing OnePlus Pad 3 on sextant

- [x] Read ADB device enumeration, model, API, ABI and `ro.lineage.version` with explicit serial selection.
- [x] Confirm a real device-specific official LineageOS target and crDroid listings exist.
- [ ] Record sanitized build fingerprint, security patch, SELinux, native app identity, permission state and OS behavior in an **ephemeral** test report (no serials/secrets in Git).
- [ ] Run allowed read-only Host MCP smoke with the exact device selection; distinguish pass/fail/skipped in report.
- [ ] Run Native debug APK lifecycle, consent, foreground/background, screenshots, UI tree, diagnostics and reconnect tests **only through existing granted device-operation gates**. Denied paths are acceptance tests too.
- [ ] Re-run E2E on the exact as-installed LineageOS build before adding alternative ROM test runs.

### P1 — first-generation OnePlus Pad and Xiaomi Pad 6 Pro

- [ ] Attach **one tablet at a time** and record exact model/codename, ROM, API, security patch, Treble and normal ADB status. Do not derive the ADB serial from the expected model.
- [ ] Run the same Host/Native E2E suite on each **as currently installed**. Preserve baselines and record hardware/ROM-specific deviations.
- [ ] For the original OnePlus Pad, investigate whether any **actual maintained device-specific custom ROM** appears; do **not** mark a generic GSI as certified.
- [ ] For `liuqin`, compare Paranoid Android, unofficial LineageOS and PixelOS only after independent hash/source/recovery review and a confirmed hardware match.
- [ ] Capture ROM-specific deltas: USB/ADB stability, accessibility consent, projection/screenshot behavior, background process restrictions, power policies, split-screen/tablet orientation, startup after reboot, and Host↔Native lease/fence behavior.

### P2 — optional ROM transitions (no execution authorization)

- [ ] Obtain independent approval **for each target and exact image**, reviewed backup/rollback plan, bootloader state, verified download checksums, compatible firmware and image partition map.
- [ ] Preserve at least one working recovery path and original firmware before any destructive experiment.
- [ ] Test alternative ROMs **serially**, retest boot/ADB/consent/Native and Host E2E, compare with preserved baseline, then intentionally return to a known-good state as necessary.
- [ ] Do not add ROM-specific images to generic Android Studio AVDs; maintain an **independent ARM64 emulator build** for platform-level LineageOS testing.

## Test evidence schema (per actual run)

Include test date, device **alias**, verified model/codename, ROM/version/build/Android API, host OS/architecture, test-suite commit, exact test set, counts (`passed` / `failed` / `skipped`), confidence source (`observed` or `publisher-reported`), critical permission state and non-sensitive failures. Never publish a USB serial, build diagnostics, screenshots, data partitions, pairing credentials or tokens.

**Exit rule:** A distribution is **eligible** when we have verified device-targeted build provenance and a recovery plan. It is **tested** only after boot, ADB, deployment, MCP operations and negative authorization paths are actually exercised. A vendor's marketing page or a ROM download entry alone is not a pass.

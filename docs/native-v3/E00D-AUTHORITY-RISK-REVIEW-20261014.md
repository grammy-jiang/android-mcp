# E00.d — Twenty-family Android authority and risk ownership audit

**Scope:** Source-backed classification; not a granted Android permission,
production release, independent security signoff or externally approved physical action.

Each capability is assigned a required Host scope, actual Android OS
authorization mechanism (or explicit absence thereof), accountable
engineering owner role, user/operator authority, separately owned
independent review role, permitted environment and bounded fallback.

All 20 families are NOT_DONE for product acceptance and all 20 independent
review statuses remain PENDING_EXTERNAL. No model-generated consent,
synthetic Android grant, arbitrary shell or physical device shortcut is allowed.

## Responsibility matrix

| Family | Profile and Host scope | Real Android mechanism | OS UI callback? | Scoped operator approval? | Native write fence? | Accountable owner |
| --- | --- | --- | --- | --- | --- | --- |
| N01 | S0_STATUS_ONLY / status | NONE_STATUS_ONLY | no | no | no | security_architect |
| N02 | S1_PAIRED_READ / read | BUILD_FRAMEWORK_SDK_READ | no | no | no | native_android_owner |
| N03 | S1_PAIRED_READ / read | BATTERYMANAGER_STATFS_DISPLAYMETRICS_CONNECTIVITY | no | no | no | native_android_owner |
| N04 | S1_PAIRED_READ / read | PACKAGEMANAGER_APPOPS_PERMISSION_READ | no | no | no | native_android_owner |
| N05 | S1_PAIRED_READ / read | PACKAGEMANAGER_VISIBLE_SCOPED_QUERIES | no | no | no | native_android_owner |
| N06 | S1_PAIRED_READ / read | APP_OWN_ACTIVITY_SERVICE_STATE | no | no | no | native_android_owner |
| N07 | S2_USER_CONSENTED_READ / user_consented | ACCESSIBILITY_SETTINGS_SERVICE_CALLBACK | yes | no | no | android_accessibility_feature_owner |
| N08 | S3_APPROVED_CONTROL / approved_control | ACCESSIBILITY_GESTURES_SCOPED_SERVICE | yes | yes | yes | android_accessibility_feature_owner |
| N09 | S2_USER_CONSENTED_READ / user_consented | MEDIAPROJECTION_CREATE_SCREEN_CAPTURE_INTENT | yes | no | no | android_capture_feature_owner |
| N10 | S2_USER_CONSENTED_READ / user_consented | MEDIAPROJECTION_FOREGROUND_RECORDING | yes | no | no | android_capture_feature_owner |
| N11 | S2_USER_CONSENTED_READ / user_consented | SAF_OPEN_AND_CREATE_DOCUMENT | yes | no | no | android_file_feature_owner |
| N12 | S3_APPROVED_CONTROL / approved_control | EXPLICIT_EXPORTED_INTENT_LAUNCH | no | yes | yes | native_android_owner |
| N13 | S2_USER_CONSENTED_READ / user_consented | OPTIONAL_NOTIFICATION_SENSOR_RUNTIME_PERMISSION | yes | no | no | android_optional_permission_owner |
| N14 | S1_PAIRED_READ / read | OWN_PROCESS_DIAGNOSTICS_RETENTION | no | no | no | native_privacy_owner |
| N15 | S3_APPROVED_CONTROL / approved_control | PACKAGEINSTALLER_PENDING_USER_ACTION | yes | yes | yes | android_installation_owner |
| N16 | S0_STATUS_ONLY / status | SERVICE_ACTIVITY_NOTIFICATION_STOP | no | no | no | native_android_owner |
| N17 | S1_PAIRED_READ / read | KEYSTORE_USER_PAIRED_HOST_CERT_TLS | no | yes | no | identity_protocol_owner |
| N18 | S3_APPROVED_CONTROL / approved_control | DURABLE_FENCE_LEASE_DISPATCH_RECHECK | no | yes | yes | native_lease_owner |
| N19 | EXTERNAL_MANAGED_LAB / managed_lab | DEVICEPOLICYMANAGER_MANAGED_LAB | yes | yes | yes | managed_android_lab_owner |
| N20 | UNSUPPORTED_APK_HOST_FALLBACK / host_maintenance | NO_NATIVE_ROOT_ROM_BOOTLOADER_API | no | yes | no | host_maintenance_owner |

## Non-negotiable platform distinctions

- N01 and N16: status and on-device visible Stop must not imply access
  to privileged Tools or a paired identity. Remote read/control still requires
  a separately authenticated principal.
- N02–N06 and N14: actual Android read-only Framework API requires
  authenticated Host read scope and an independent system oracle;
  no invented generic Android consent screen.
- N07–N08: Accessibility must be enabled by the user in Android Settings
  and confirmed by a connected Android AccessibilityService callback;
  N08 gestures additionally require exact per-action authority and a Native fence.
- N09–N10: Android MediaProjection consent token is one-time user-approved
  ActivityResult. API34+ foreground-service type and actual onStop callback
  are required; a synthetic projection token does not qualify.
- N11: SAF grants authorize only selected document URIs. An export/write
  additionally requires operator approval and durable Native lease before
  any ContentResolver effect. Synthetic permission or broad filesystem read
  cannot replace user-selected ActivityResult.
- N12: launch an exact exported Intent with operator and Native lease.
  Ordinary app launch does not invent a generic Android OS permission prompt.
- N13: permission-sensitive optional reads must use real per-API runtime or
  Settings approval when required; absent sensors become honest unavailable.
- N15: PackageInstaller STATUS_PENDING_USER_ACTION and actual Android
  foreground-user acceptance are required; silent shell install is forbidden.
- N17–N18: verified mutually authenticated Host/Native identity and
  authoritative Native dispatch fence cannot be replaced by localhost,
  Origin headers or ADB port forwarding. Independently reviewed key
  enrollment, revocation and session expiration remain undone.
- N19: managed DeviceOwner action is external-gated to a fresh dedicated
  owner-controlled test AVD; never adopt a physical device or generic APK.
- N20: ordinary APK Root/ROM/Bootloader changes are unsupported;
  only independently approved **Host read-only** diagnostics and
  owner-supervised manual procedures are permitted fallback.

## Automated negative policy evidence

The package runs adversarial unit tests that intentionally try to erase
capabilities, duplicate IDs, forge security signoff, replace the Root-only
Host fallback with Native privileged code, claim model-created Android
approval, act without operator/lease/reviewer approval, substitute
a SAF write grant, or target physical devices. Every such attempted
promotion is rejected by the E00.d policy validator.

Reproducible local invocation:

~~~bash
python3 -m unittest discover -s tests -p test_native_v3_authority_matrix.py -v
python3 scripts/native_v3_authority_matrix.py --matrix docs/native-v3/v3-authority-risk-register.json --registry docs/native-v3/Android_Native_MCP_E2E_Acceptance_Registry_V3_2026-10-14.json
python3 scripts/native_v3_todo.py --repo .
~~~

This classifier is NOT a runtime grant issuer: even a theoretically valid
request returns PLAN_ONLY_NOT_LIVE_APPROVAL until the real Host/Native
credential, OS callback, user authorization and independent review are
implemented and observed on a verified exclusively owned Android target.

## Mandatory open dependencies

- E00.c independent attestation admission and release-signoff separation.
- E01.c real user-visible Android approval/denial/revocation callbacks.
- E02.c–g real paired user fingerprint/key lifecycle and hostile-peer tests.
- E08 native authoritative fence; sensitive N08/N11/N12/N15 action gates.
- N19 independent managed lab owner review, N20 Host-only fallback.
- Per-capability API 30/33/34/36 positive, negative and fault recovery
  evidence. These are **not** closed by this risk classification.

**Engineering classification: complete when this matrix validates and is
integrated against the same source tree. Production release remains
PRODUCT_INCOMPLETE, independent review PENDING_EXTERNAL.**

# Native N8.a — managed-device / Device Owner feasibility boundary

**Status: ordinary non-DeviceOwner APK — unsupported in production.**
The Native runtime has no DeviceAdminReceiver, `BIND_DEVICE_ADMIN`
receiver declaration, device provisioning, admin takeover, enrollment or
policy-change Tool. No DevicePolicyManager mutation can occur.

A private Kotlin feasibility model accepts deliberately synthetic,
externally injected environment data. No `modelRoleClaim` can create a
DeviceOwner role. Unknown/false own-owner status is unsupported or unavailable;
only an entirely fake, confirmed own-DeviceOwner + declared admin receiver +
disposable owned device + fake human/caller approval fixture returns the
bounded capability names `policy_audit`, `lock_task`, `app_restrictions` as
**PLAN_ONLY**. All wipe, lock, account, policy, silent-install and
self-provision requests always return DENIED, including against a fake owner.
This model never operates on Android DevicePolicyManager state.

The optional Android-side internal read-only probe can query **only whether
this app package itself is Device Owner** (`isDeviceOwnerApp(context.packageName)`).
The result is passed through the policy with admin-receiver and owner proof
hard-disabled, so the production adapter always remains unsupported.
This probe is NOT registered as a public Native MCP Tool or runtime admin.
No other package or personal/work-profile data is enumerated. All receipts
report side effects false; no identities or secrets are encoded.

T-N8A-01..06 were RED as six meaningful behavioral failures on the
permissive stub, then GREEN. Three extra Kotlin tests check missing
receiver/owner/caller, redacted metadata and 40 concurrent fake checks;
seven Python source/Manifest/Tool/OS-call negative checks validate the
production boundary. Full macOS JDK17/SDK36 Native/Host quality gate and
four verified API30/33/34/36 QEMU baseline acceptance are required.

**Acceptance limitations:** baseline APK smoke on QEMU does **not** provision
or emulate a real corporate Device Owner. Genuine managed-device provisioning,
enterprise enrollment, OS-specific Device Owner policies, wiping, locking,
OEM policy differences and any real policy mutation are NOT tested and remain
separately unsupported/blocked pending explicit owner approval and external
independent privilege review. No physical device or corporate policy is changed.

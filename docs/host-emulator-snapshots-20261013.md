# Host H3.d — authenticated synthetic emulator snapshot records

## Boundaries and operator activation

The optional host_emulator_snapshot Tool is disabled by default.
Its operator flag --emulator-snapshot-fixture requires the same
H3.b private AVD, pinned installed SDK image, existing local license
receipt, and trusted owner used by a private H2.d durable-job store.
The public tool cannot select a filesystem path, process ID, emulator
executable, Android device, shell command or alternate owner.

This work package manages only small synthetic snapshot **metadata**.
It does not issue real emulator save/load, disk rollback, process
fault injection or physical Android writes. Every response declares
possible_emulator_state_change=false, real_snapshot_execution_enabled=false
and physical_device_writes_enabled=false. Restores report simulated,
not a genuine emulator state transition. The fault_plan operation
returns an inert, named boot-delay, network-disconnect or crash plan.

## Record provenance and private storage

An exact H3.b owner-signed AVD handle is required for each operation.
The system image file, source metadata, API, ABI and existing license
receipt are revalidated. Only a dedicated operator-owned AVD root is
eligible. The owner key remains in its private 0600 file and is never
returned through MCP.

A synthetic snapshot is a small, immutable, owner-authenticated JSON
receipt: AVD handle, pseudonymous owner, API, ABI, pinned binary system
image SHA-256, snapshot name, format version, synthetic fixture digest
and a derived opaque handle. A stable HMAC signs each record. The
snapshot file is a private 0600, owned, single-link file under the
existing dedicated H3.b root, with a fixed validated name. Creation
uses no-follow exclusive file creation and a bounded record size.
Unknown, symlinked, hardlinked, altered, incompatible or old-version
records cannot be adopted, restored, deleted or silently migrated.

A common private advisory lock serializes H3.b provisioning and H3.d
snapshot operations. At most twelve snapshot records per owned AVD
are accepted; unrelated existing files are never overwritten.
H3.b AVD deletion is denied while any snapshot record remains. Only
individual verified metadata files can be unlinked. The manager
never recursively removes snapshot directories or another AVD's
files and does not interpret actual emulator snapshot binaries.

Create, simulated restore, and delete are bound to H2.d durable job
idempotency and a single worker claim. Duplicate completed requests
replay metadata; unresolved or uncertain operations fence all new
mutating snapshot jobs. Storage errors and post-write journal failures
are reported as failed or uncertain according to whether a write may
have taken place. There is no blind replay of unknown effects.

## Tests and deferred real activation

T-H3D-01 through T-H3D-06 and supplemental fault-injection tests
cover HMAC owner binding, verified source-image identity, snapshots
with create/list/simulated-restore/delete, foreign and malformed
records, symlink/hardlink attacks, incompatible API/ABI/version,
quota, concurrent creation, partial writes, timeout and cancellation,
MCP contract schema, disabled defaults and a localhost HTTP fixture.
No existing Native AVD, real QEMU process or physical Android device
is controlled by the test suite.

Real snapshot save/load and genuine emulator fault simulation remain
disabled pending their own independently reviewed process ownership,
port leasing, verified QEMU and real disposable-device acceptance.
Host acceptance requires Python 3.11–3.14 on both macOS ARM64 and
sextant Linux ARM64, Git hooks, quality policy, wheel/sdist package
smoke, an exact main-branch merge, and post-merge verification.

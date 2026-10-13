# H3.f — private synthetic-only debug APK deployment

## Capability and explicit opt-in

The Host MCP Tool `host_emulator_debug_deploy` is **off by default**.
The operator enables its inert planning surface with
`--emulator-debug-plan --debug-package-id org.example.synthetic.debug`,
in addition to the already approved H3.b disposable AVD provisioning,
H3.c plan-only emulator lifecycle, H2.d owner-scoped durable jobs,
and H2.c private artifacts. The AVD and job-store owners must agree.
The operator-pinned test package is fixed before server startup.
Neither arbitrary Android package IDs nor executable names, shell
commands, APK filesystem paths or serial numbers are Tool arguments.

**Real APK installation, Activity launch, force-stop, uninstall, USB
fallback, adb shell, SDK update and emulator state mutation remain
completely disabled in production.** Public CLI composition injects
no execution runner. The `plan` action observes only strict private
metadata. Install/launch/uninstall/cleanup/cancel are usable only
in explicitly injected Python integration-test synthetic fixtures.
All responses declare `real_deployment_enabled=false`,
`physical_device_writes_enabled=false`,
`synthetic_fixture_only=true` and the
`disposable_emulator_only` target scope.

## Input and fake signature checks

Every request verifies exact HMAC ownership of a single H3.b disposable
AVD and its currently pinned system-image SHA, API, ABI and existing
SDK license receipt. A synthetic operation additionally checks H3.c's
live, in-process fixture ownership and original durable lifecycle job
before AND after the runner. A string resembling `emulator-5554`, a
physical USB serial or an older process PID cannot serve as a lease.

The APK must already exist under an operator-fixed private artifact
owner, with the APK MIME type, exact SHA-256 and a bounded ZIP archive
that has safe entry names, valid CRC and a literal, fully qualified
manifest package. A synthetic test-only HMAC over every allowed fixture
member binds its contents to the private AVD owner key. This marker
is **not** an Android v1/v2/v3/v4 APK signature, and it must never be
presented as genuine platform signing validation. It serves only to
reject missing or modified test fixture inputs. Only the pinned
synthetic package and matching ABI are permitted. API 26–40 is the
bounded fixture-supported range; no arbitrary install flags are
accepted. If the APK artifact is revoked during a fixture operation,
the resulting job is uncertain, never an install success.

## Fixed test actions, receipts and recovery

A test harness may inject a finite, fake-only runner. Its entire
argument vector is constructed by the Host from the validated action,
exact AVD name, in-memory confirmed lifecycle job, private APK digest
and approved package ID. It is not a real `adb install` invocation.
The expected response is a bounded, exact synthetic JSON envelope,
not untrusted raw stdout. Malformed, truncated, mismatched, nonzero or
stderr-containing responses are never marked as successful.

Synthetic install produces a bounded private JSON report with the
exact job ID, AVD handle, lifecycle session, package, APK digest and
`synthetic_installed` state. Launch/uninstall/cleanup require the
original opaque install-report handle, freshly read from the same
private artifact owner, plus matching ephemeral in-process installed
state. An expired, revoked, foreign or mismatched receipt, or a
restarted controller lacking an active session, is denied. Synthetic
uninstall or cleanup drops only its own in-memory fixture state.
No real package is uninstalled. Replayed successful jobs return an
**historical** report receipt with current state `unknown`, not a
claim that the fake package remains installed.

The existing H2.d ledger binds every request to action, lifecycle
job, image, package, APK SHA, original install report and owner handle.
A common private cross-process lock shared with H3.e ensures that
instrumentation and debug deployment on the same disposable AVD do
not race. Any active unrelated or uncertain Host job fences execution.
Timeouts, revoked inputs, process exit, transport-like runner faults
and interrupted private report/journal commits are fail-closed.
Cancellation requires the *original* action, request ID, precise job
ID and exact original plan. It can neither cancel another Host job nor
blindly replay a previously uncertain operation. No raw test logs,
filesystem paths or private owner keys are returned through MCP.

## Test scope and real-device limitations

T-H3F-01 through T-H3F-06 and supplemental cases cover fixed fake
install argv/receipts, physical serial denial, test-HMAC absence,
wrong package/ABI/API, invalid flags/path, exact launch/uninstall,
replay after cleanup, job-storage failure, timeout, cancellation,
concurrent operations, private artifact revocation, CLI default denial
and a genuine localhost MCP server fixture. They do not exercise
Android's package installer, Activity Manager, platform APK signing
or physical device permission prompts; those are separate safety gates.

Integration requires exact committed-SHA Python 3.11–3.14 Host
quality gates on macOS ARM64 and sextant Linux ARM64, both Git hook
stages, independent wheel/sdist clean-install and doctor checks,
main-branch race verification and post-merge checks. Unexecuted hosted
GitHub Actions must not be presented as successful acceptance.

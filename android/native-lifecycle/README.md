# Native process-local service lifecycle

This **SDK-free** Kotlin module models foreground service command ordering.
It does not import Android APIs, own sockets, authenticate callers, or
authorize device changes. Its monotonic generation is an operation token,
not a Host/Native distributed lease or durable secret.

The service model serializes START/STOP into generation-tagged commands.
Android's Service runs actual socket operations on one serial worker and
reports completion only after real listener readiness/closure.

The separate `LocalPortOwner` model protects ownership of the single
process-local loopback port. `reserve` only succeeds from FREE; a real
listener-readiness probe is required before `confirmReady`, and
`confirmStopped` requires proof that the kernel socket is no longer bound.
If shutdown is uncertain, the owner remains UNKNOWN and new starts are
rejected until the original owner verifies release or the process exits.
Neither model is a Host/Native distributed Lease or caller credential.

Run `./android/gradlew --project-dir android :native-lifecycle:test`.
This module is opt-in for the Android application dependency but is included
in the default SDK-free Gradle build and `scripts/check-native.sh`.

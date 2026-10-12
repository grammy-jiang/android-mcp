# Native process-local service lifecycle

This **SDK-free** Kotlin module models foreground service command ordering.
It does not import Android APIs, own sockets, authenticate callers, or
authorize device changes. Its monotonic generation is an operation token,
not a Host/Native distributed lease or durable secret.

The model serializes START/STOP requests into generation-tagged commands.
Android's Service remains responsible for running the commands on one
worker and reporting completion only after real listener readiness/closure.
Uncertain shutdown must remain FAILED_CLOSED; never release socket ownership
on a mere stop request.

Run `./android/gradlew --project-dir android :native-lifecycle:test`.
This module is opt-in for the Android application dependency but is included
in the default SDK-free Gradle build and `scripts/check-native.sh`.

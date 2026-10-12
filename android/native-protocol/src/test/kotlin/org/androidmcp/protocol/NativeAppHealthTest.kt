package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeAppHealthTest {
    private fun input(
        mode: NativeAppMode = NativeAppMode.FOREGROUND_SERVICE,
        phase: NativeAppPhase = NativeAppPhase.RUNNING,
    ) = NativeAppHealthInput(
        apiLevel = 36,
        mode = mode,
        ownerPhase = phase,
        listenerReady = true,
        foregroundNotificationPresent = true,
        processAlive = true,
        elapsedRealtimeMs = 125_000,
        startedElapsedMs = 100_000,
    )

    @Test
    fun tN1C01ActivityOrFgServiceRequiresActualPortAndNotification() {
        val fgs = NativeAppHealthSnapshots.evaluate(input())
        assertEquals(NativeAppPhase.RUNNING, fgs.phase)
        assertEquals(25_000L, fgs.uptimeMs)
        assertTrue(fgs.endpointReady)
        val activity = NativeAppHealthSnapshots.evaluate(input(
            mode = NativeAppMode.ACTIVITY
        ).copy(foregroundNotificationPresent = false))
        assertEquals(NativeAppPhase.RUNNING, activity.phase)
        assertTrue(activity.endpointReady)
        val noNotification = NativeAppHealthSnapshots.evaluate(
            input().copy(foregroundNotificationPresent = false)
        )
        assertFalse(noNotification.endpointReady)
        assertEquals(NativeAppPhase.FAILED_CLOSED, noNotification.phase)
    }

    @Test
    fun tN1C02ExplicitStopNotificationAndProcessDeathAreDistinct() {
        for (reason in listOf(NativeStopCause.USER, NativeStopCause.NOTIFICATION, NativeStopCause.PROCESS_DEATH)) {
            val stopped = NativeAppHealthSnapshots.evaluate(
                input().copy(
                    ownerPhase = NativeAppPhase.STOPPED,
                    processAlive = reason != NativeStopCause.PROCESS_DEATH,
                    listenerReady = false,
                    foregroundNotificationPresent = false,
                    stopCause = reason,
                )
            )
            assertEquals(NativeAppPhase.STOPPED, stopped.phase)
            assertEquals(reason, stopped.stopCause)
            assertFalse(stopped.endpointReady)
            assertNull(stopped.uptimeMs)
        }
    }

    @Test
    fun tN1C03FailedBindTimeoutAndUnverifiedShutdownCannotAppearReady() {
        val cases = listOf(
            NativeHealthError.PORT_BUSY,
            NativeHealthError.START_TIMEOUT,
            NativeHealthError.UNVERIFIED_SHUTDOWN,
        )
        for (failure in cases) {
            val snapshot = NativeAppHealthSnapshots.evaluate(
                input().copy(ownerPhase = NativeAppPhase.STARTING, error = failure)
            )
            assertFalse(snapshot.endpointReady)
            assertEquals(NativeAppPhase.FAILED_CLOSED, snapshot.phase)
            assertEquals(failure, snapshot.error)
            assertFalse(snapshot.encode().contains("port=38765"))
        }
    }

    @Test
    fun tN1C04OldApiAndNewProcessCannotClaimOldFgsUptime() {
        val old = NativeAppHealthSnapshots.evaluate(input().copy(apiLevel = 30))
        assertEquals(NativeAppPhase.UNSUPPORTED, old.phase)
        assertFalse(old.endpointReady)
        assertNull(old.uptimeMs)
        val fresh = NativeAppHealthSnapshots.evaluate(
            input().copy(
                ownerPhase = NativeAppPhase.STOPPED,
                processAlive = false,
                startedElapsedMs = 5,
                elapsedRealtimeMs = 9_000,
            )
        )
        assertEquals(NativeAppPhase.STOPPED, fresh.phase)
        assertEquals(NativeStopCause.PROCESS_DEATH, fresh.stopCause)
        assertNull(fresh.uptimeMs)
    }

    @Test
    fun tN1C05HealthSnapshotContainsNoPidStacktraceOrCredentials() {
        val detail = NativeAppHealthSnapshots.evaluate(input()).encode().lowercase()
        for (forbidden in listOf(
            "pid", "uid", "stacktrace", "exception", "private_path",
            "filesdir", "serial", "token", "password", "credential",
            "account", "http://", "127.0.0.1", "hostname",
        )) {
            assertFalse(detail.contains(forbidden))
        }
        assertTrue(detail.toByteArray().size < 1024)
        val root = Json.parseToJsonElement(detail).jsonObject
        assertEquals("1", root.getValue("schema_version").jsonPrimitive.content)
        assertEquals("foreground_service", root.getValue("mode").jsonPrimitive.content)
        assertEquals("running", root.getValue("phase").jsonPrimitive.content)
    }

    @Test
    fun tN1C06PublicMcpV1AndErrorsNeverDependOnFakeHealth() {
        val stopped = NativeAppHealthSnapshots.evaluate(
            input(phase = NativeAppPhase.FAILED_CLOSED).copy(
                listenerReady = false,
                error = NativeHealthError.INTERNAL,
            )
        )
        assertEquals("internal", Json.parseToJsonElement(stopped.encode())
            .jsonObject.getValue("error").jsonPrimitive.content)
        assertFalse(stopped.endpointReady)
        val baseline = NativeLocalStatus.encode()
        assertTrue(baseline.contains("android.native.loopback_status"))
        assertFalse(baseline.contains("process_health"))
        val guard = NativeLocalCallerGuard()
        val caller = LocalHttpRequest(origin = "http://127.0.0.1:38765")
        assertFalse(guard.authorizeSensitive(caller, "native_app_health").allowed)
    }
}

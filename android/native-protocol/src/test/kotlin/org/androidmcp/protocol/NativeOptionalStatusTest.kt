package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeOptionalStatusTest {
    private fun input(api: Int = 36) = OptionalStatusInput(
        apiLevel = api, sampledElapsedMs = 100_000,
        batteryPercent = 64, displayWidthPx = 1080, displayHeightPx = 1920,
        networkPermissionGranted = false, networkValidated = null,
        notificationsPermissionGranted = false,
        motionSensorSupported = false,
    )

    @Test
    fun tN4F01BatteryDisplayAndNetworkHavePreciseUnitsAndPermissionDenial() {
        val snapshot = NativeOptionalStatusSession().snapshot(input())
        assertEquals(1, snapshot.schemaVersion)
        assertEquals(36, snapshot.apiLevel)
        assertEquals(100_000L, snapshot.sampledElapsedMs)
        assertEquals(64, snapshot.batteryPercent)
        assertEquals(1080, snapshot.displayWidthPx)
        assertEquals(1920, snapshot.displayHeightPx)
        assertEquals(OptionalReadiness.AVAILABLE, snapshot.readiness(OptionalCapability.BATTERY))
        assertEquals(OptionalReadiness.AVAILABLE, snapshot.readiness(OptionalCapability.DISPLAY))
        assertEquals(OptionalReadiness.PERMISSION_DENIED, snapshot.readiness(OptionalCapability.CONNECTIVITY))
        val wire = Json.parseToJsonElement(snapshot.encode()).jsonObject
        assertEquals("android", wire.getValue("runtime").jsonPrimitive.content)
        assertEquals("100000", wire.getValue("sampled_elapsed_ms").jsonPrimitive.content)
        assertEquals("permission_denied", wire.getValue("connectivity").jsonPrimitive.content)
    }

    @Test
    fun tN4F02LocationMicContactsAndNotificationContentDeniedEvenFakeGrant() {
        val sample = NativeOptionalStatusSession().snapshot(input().copy(
            networkPermissionGranted = true,
            networkValidated = true,
            notificationsPermissionGranted = true,
            motionSensorSupported = true,
        ))
        for (capability in listOf(
            OptionalCapability.LOCATION,
            OptionalCapability.MICROPHONE,
            OptionalCapability.CONTACTS,
            OptionalCapability.NOTIFICATION_CONTENT,
        )) {
            assertEquals(OptionalReadiness.PERMISSION_DENIED, sample.readiness(capability))
        }
        assertFalse(sample.encode().contains("notification_text"))
        assertFalse(sample.encode().contains("precise_location"))
    }

    @Test
    fun tN4F03BackgroundOrModelPollRequestCannotStartPersistentSensorLoop() {
        val session = NativeOptionalStatusSession()
        assertEquals(OptionalReadiness.DISABLED,
            session.sampleSynthetic(input().copy(foreground = false)))
        assertEquals(0, session.eventCount())
        assertFalse(session.realSensorSubscriptionAllowed())
        val stopped = session.snapshot(input().copy(foreground = false))
        assertEquals(OptionalReadiness.DISABLED, stopped.readiness(OptionalCapability.BATTERY))
        assertNull(stopped.batteryPercent)
    }

    @Test
    fun tN4F04ApiMatrixRevocationAndMalformedValuesRemainExplicitUnavailable() {
        for (api in listOf(30, 33, 34, 36)) {
            val snapshot = NativeOptionalStatusSession().snapshot(input(api))
            assertEquals(api, snapshot.apiLevel)
            assertEquals(OptionalReadiness.PERMISSION_DENIED,
                snapshot.readiness(OptionalCapability.CONNECTIVITY))
        }
        assertEquals(OptionalReadiness.UNSUPPORTED,
            NativeOptionalStatusSession().snapshot(input(29))
                .readiness(OptionalCapability.BATTERY))
        val bad = NativeOptionalStatusSession().snapshot(input().copy(
            batteryPercent = 123, displayWidthPx = -10, displayHeightPx = 999_999,
            sampledElapsedMs = -1, networkPermissionGranted = null,
        ))
        assertNull(bad.batteryPercent)
        assertNull(bad.displayWidthPx)
        assertNull(bad.displayHeightPx)
        assertNull(bad.sampledElapsedMs)
        assertEquals(OptionalReadiness.UNAVAILABLE,
            bad.readiness(OptionalCapability.BATTERY))
        assertEquals(OptionalReadiness.PERMISSION_DENIED,
            bad.readiness(OptionalCapability.CONNECTIVITY))
    }

    @Test
    fun tN4F05RateLimitQueueCapacityAndFgsStopUnsubscribeFakeSamples() {
        for (reason in OptionalStopReason.entries) {
            val session = NativeOptionalStatusSession()
            for (i in 0 until 16) {
                assertEquals(OptionalReadiness.AVAILABLE,
                    session.sampleSynthetic(input().copy(sampledElapsedMs = 100_000L + i * 1000)))
            }
            assertEquals(16, session.eventCount())
            assertEquals(OptionalReadiness.THROTTLED,
                session.sampleSynthetic(input().copy(sampledElapsedMs = 116_000)))
            session.stop(reason)
            assertEquals(0, session.eventCount())
            assertEquals(OptionalReadiness.STOPPED,
                session.sampleSynthetic(input().copy(sampledElapsedMs = 120_000)))
            assertFalse(session.realSensorSubscriptionAllowed())
        }
        val limited = NativeOptionalStatusSession()
        assertEquals(OptionalReadiness.AVAILABLE, limited.sampleSynthetic(input()))
        assertEquals(OptionalReadiness.THROTTLED,
            limited.sampleSynthetic(input().copy(sampledElapsedMs = 100_100)))
    }

    @Test
    fun tN4F06PublicJsonContainsNoLocationNearbyIdsOrNotificationText() {
        val status = NativeOptionalStatusSession().snapshot(input())
        val encoded = status.encode().lowercase()
        for (secret in listOf(
            "ssid", "bssid", "mac_address", "device_id",
            "android_id", "serial_number", "latitude", "longitude",
            "precise_coordinates", "notification_text", "contact_name",
            "email_address", "account_number", "token",
        )) assertFalse(encoded.contains(secret))
        assertTrue(encoded.toByteArray().size < 4096)
        assertEquals(listOf("device_status"),
            NativeToolProfiles().liveTools(true).map { it.name })
        assertFalse(NativeLocalStatus.encode().contains("optional_sensor"))
    }
}

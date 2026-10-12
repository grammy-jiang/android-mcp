package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeSystemSnapshotTest {
    private fun inputs(api: Int = 36) = NativeSystemInputs(
        apiLevel = api,
        elapsedMs = 100_000L,
        batteryPercent = 75,
        appStorageAvailableBytes = 5_000_000_000L,
        appStorageTotalBytes = 10_000_000_000L,
        displayWidthPx = 2560,
        displayHeightPx = 1600,
        network = NativeNetworkReadiness.PERMISSION_DENIED,
    )

    @Test
    fun tN1B01BatteryStorageDisplayNetworkHaveTypedUnitsAndTimestamp() {
        val result = NativeSystemSnapshots.normalize(inputs())
        assertEquals(1, result.schemaVersion)
        assertEquals(36, result.apiLevel)
        assertEquals(100_000L, result.elapsedMs)
        assertEquals(75, result.batteryPercent)
        assertEquals(5_000_000_000L, result.appStorageAvailableBytes)
        assertEquals(10_000_000_000L, result.appStorageTotalBytes)
        assertEquals(2560, result.displayWidthPx)
        assertEquals(1600, result.displayHeightPx)
        assertEquals(NativeSystemAvailability.PARTIAL, result.availability)
        val wire = Json.parseToJsonElement(result.encode()).jsonObject
        assertEquals("android", wire.getValue("runtime").jsonPrimitive.content)
        assertEquals("100000", wire.getValue("sampled_elapsed_ms").jsonPrimitive.content)
        assertEquals("5000000000", wire.getValue("app_storage_available_bytes").jsonPrimitive.content)
    }

    @Test
    fun tN1B02MissingServiceAndPermissionDeniedNetworkReportUnavailable() {
        val missing = NativeSystemSnapshots.normalize(
            inputs().copy(
                batteryPercent = null,
                appStorageAvailableBytes = null,
                appStorageTotalBytes = null,
                displayWidthPx = null,
                displayHeightPx = null,
                network = NativeNetworkReadiness.PERMISSION_DENIED,
            )
        )
        assertEquals(NativeSystemAvailability.UNAVAILABLE, missing.availability)
        assertNull(missing.batteryPercent)
        assertNull(missing.appStorageAvailableBytes)
        assertNull(missing.displayWidthPx)
        assertEquals(NativeNetworkReadiness.PERMISSION_DENIED, missing.network)
        assertFalse(missing.encode().contains("ssid"))
        val offline = NativeSystemSnapshots.normalize(inputs().copy(network = NativeNetworkReadiness.OFFLINE))
        assertEquals(NativeNetworkReadiness.OFFLINE, offline.network)
    }

    @Test
    fun tN1B03NegativeOrHugeValuesCannotBeReportedAsPlausible() {
        val invalid = NativeSystemSnapshots.normalize(
            inputs().copy(
                elapsedMs = -1,
                batteryPercent = 101,
                appStorageAvailableBytes = Long.MAX_VALUE,
                appStorageTotalBytes = Long.MAX_VALUE,
                displayWidthPx = -100,
                displayHeightPx = 100_000,
            )
        )
        assertNull(invalid.elapsedMs)
        assertNull(invalid.batteryPercent)
        assertNull(invalid.appStorageAvailableBytes)
        assertNull(invalid.appStorageTotalBytes)
        assertNull(invalid.displayWidthPx)
        assertNull(invalid.displayHeightPx)
        assertEquals(NativeSystemAvailability.UNAVAILABLE, invalid.availability)
    }

    @Test
    fun tN1B04SupportedAndroidApiMatrixAndOldVersionUnsupported() {
        for (api in listOf(30, 33, 34, 36)) {
            val snapshot = NativeSystemSnapshots.normalize(inputs(api))
            assertEquals(api, snapshot.apiLevel)
            assertEquals(75, snapshot.batteryPercent)
            assertEquals(NativeSystemAvailability.PARTIAL, snapshot.availability)
        }
        val old = NativeSystemSnapshots.normalize(inputs(29))
        assertEquals(NativeSystemAvailability.UNSUPPORTED, old.availability)
        assertNull(old.apiLevel)
        assertNull(old.batteryPercent)
    }

    @Test
    fun tN1B05FreshRefreshDoesNotRetainPriorServiceOrNetworkReadings() {
        val first = NativeSystemSnapshots.normalize(inputs().copy(
            batteryPercent = 90, network = NativeNetworkReadiness.VALIDATED
        ))
        assertEquals(NativeSystemAvailability.AVAILABLE, first.availability)
        val afterStop = NativeSystemSnapshots.normalize(inputs().copy(
            elapsedMs = 101_000L,
            batteryPercent = null,
            network = NativeNetworkReadiness.PERMISSION_DENIED,
            appStorageAvailableBytes = null,
            appStorageTotalBytes = null,
        ))
        assertNull(afterStop.batteryPercent)
        assertNull(afterStop.appStorageAvailableBytes)
        assertEquals(NativeNetworkReadiness.PERMISSION_DENIED, afterStop.network)
        assertEquals(101_000L, afterStop.elapsedMs)
        assertEquals(NativeSystemAvailability.PARTIAL, afterStop.availability)
    }

    @Test
    fun tN1B06DeniedMcpProfileNeverLeaksSsidOrLocationOrDeviceIds() {
        val snapshot = NativeSystemSnapshots.normalize(inputs())
        val encoded = snapshot.encode().lowercase()
        for (forbidden in listOf(
            "ssid", "bssid", "mac_address", "wifi", "latitude", "longitude",
            "location", "network_id", "android_id", "device_id", "serial", "ip_address",
        )) {
            assertFalse(encoded.contains(forbidden))
        }
        assertTrue(encoded.toByteArray().size < 4096)
        val guard = NativeLocalCallerGuard()
        val caller = LocalHttpRequest(origin = "http://127.0.0.1:38765")
        assertFalse(guard.authorizeSensitive(caller, "native_system_snapshot").allowed)
        assertFalse(NativeLocalStatus.encode().contains("battery_percent"))
    }
}

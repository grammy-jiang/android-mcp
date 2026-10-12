package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeLocalStatusTest {
    @Test
    fun minimalStatusRoundTripsThroughSharedDecoder() {
        val status = DeviceStatusCodec.decode(NativeLocalStatus.encode())
        assertEquals(1, status.version)
        assertEquals("android", status.runtime)
        assertTrue(status.capabilities.getValue("android.native.loopback_status"))
        assertFalse(status.capabilities.getValue("android.accessibility.act"))
        assertFalse(status.capabilities.getValue("android.accessibility.observe"))
        assertFalse(status.capabilities.getValue("android.privileged"))
        assertTrue(status.devices.isEmpty())
        assertTrue(status.errors.isEmpty())
    }

    @Test
    fun responseHasNoDeviceOrHostInformation() {
        val root = Json.parseToJsonElement(NativeLocalStatus.encode()).jsonObject
        assertEquals(setOf("schema_version", "runtime", "capabilities", "devices", "errors"), root.keys)
        assertFalse(NativeLocalStatus.encode().contains("device_id"))
        assertFalse(NativeLocalStatus.encode().contains("adb"))
        assertFalse(NativeLocalStatus.encode().contains("serial"))
    }
}

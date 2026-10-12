package org.androidmcp.protocol

import java.nio.file.Files
import java.nio.file.Path
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class DeviceStatusCodecTest {
    private val fixtures = Path.of(System.getProperty("androidMcp.contractsRoot")).resolve("fixtures")

    @Test
    fun hostFixtureRoundTripsAsExpected() {
        val status = DeviceStatusCodec.decode(Files.readString(fixtures.resolve("host-no-device.json")))
        assertEquals(1, status.version)
        assertEquals("host", status.runtime)
        assertTrue(status.capabilities.getValue("adb.discovery"))
        assertFalse(status.capabilities.getValue("adb.connected_device"))
        assertEquals(emptyList<DeviceInfo>(), status.devices)
    }

    @Test
    fun nativeFixtureDoesNotRequireHostProperties() {
        val status = DeviceStatusCodec.decode(Files.readString(fixtures.resolve("native-example.json")))
        assertEquals("android", status.runtime)
        assertEquals(1, status.devices.size)
        assertEquals("example-native-installation", status.devices.single().deviceId)
        assertFalse(status.capabilities.getValue("android.accessibility.act"))
    }

    @Test
    fun rejectsUnsupportedContractAndOversizedResults() {
        val host = Files.readString(fixtures.resolve("host-no-device.json"))
        assertThrows(IllegalArgumentException::class.java) {
            DeviceStatusCodec.decode(host.replace("\"schema_version\": 1", "\"schema_version\": 2"))
        }
        assertThrows(IllegalArgumentException::class.java) {
            DeviceStatusCodec.decode("X".repeat(128 * 1024 + 1))
        }
    }

    @Test
    fun rejectsMalformedValuesAndMissingFields() {
        for (json in listOf("{}", "[]", "null", "{", "{\"schema_version\":true}")) {
            assertThrows(Exception::class.java) { DeviceStatusCodec.decode(json) }
        }
    }

    @Test
    fun rejectsUnknownRuntimeAndNonBooleanCapability() {
        val host = Files.readString(fixtures.resolve("host-no-device.json"))
        assertThrows(IllegalArgumentException::class.java) {
            DeviceStatusCodec.decode(host.replace("\"runtime\": \"host\"", "\"runtime\": \"other\""))
        }
        assertThrows(Exception::class.java) {
            DeviceStatusCodec.decode(host.replace("\"adb.discovery\": true", "\"adb.discovery\": 12"))
        }
    }
}

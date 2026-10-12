package org.androidmcp.protocol

import java.nio.file.Files
import java.nio.file.Path
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

class DeviceStatusCodecStrictTest {
    private val fixture = Files.readString(
        Path.of(System.getProperty("androidMcp.contractsRoot"))
            .resolve("fixtures/host-no-device.json")
    )
    private val native = """
        {
          "schema_version":1,
          "runtime":"android",
          "capabilities":{"android.accessibility.observe":false},
          "devices":[{"device_id":"native-1","state":"ready","properties":{"os":"android"}}],
          "errors":[{"code":"E1","message":"example"}]
        }
    """.trimIndent()

    @Test
    fun rejectsExtraFieldsInEveryBoundedObject() {
        val unexpected = listOf(
            fixture.replace("\"schema_version\": 1", "\"extra\": 2, \"schema_version\": 1"),
            fixture.replace("\"os\": \"macos\"", "\"extra\": 2, \"os\": \"macos\""),
            native.replace("\"device_id\":\"native-1\"", "\"extra\":0,\"device_id\":\"native-1\""),
            native.replace("\"code\":\"E1\"", "\"extra\":0,\"code\":\"E1\"")
        )
        for (json in unexpected) {
            assertThrows(Exception::class.java) { DeviceStatusCodec.decode(json) }
        }
    }

    @Test
    fun rejectsNumericAndBooleanStringCoercion() {
        val invalid = listOf(
            native.replace("\"device_id\":\"native-1\"", "\"device_id\":123"),
            native.replace("\"state\":\"ready\"", "\"state\":true"),
            native.replace("\"os\":\"android\"", "\"os\":42"),
            native.replace("\"code\":\"E1\"", "\"code\":false"),
            fixture.replace("\"architecture\": \"arm64\"", "\"architecture\": 42"),
            fixture.replace("\"version\": \"37.0.1-15733141\"", "\"version\": true")
        )
        for (json in invalid) {
            assertThrows(Exception::class.java) { DeviceStatusCodec.decode(json) }
        }
    }

    @Test
    fun rejectsInvalidHostNestedContract() {
        val invalid = listOf(
            fixture.replace("\"runtime\": \"host\"", "\"runtime\": \"host-other\""),
            fixture.replace("\"os\": \"macos\"", "\"os\": \"windows\""),
            fixture.replace("\"available\": true", "\"available\": \"true\""),
            fixture.replace("\"schema_version\": 1", "\"schema_version\": \"1\""),
            fixture.replace("\"adb.discovery\": true", "\"adb.discovery\": \"true\""),
            fixture.replace("\"errors\": []", "\"errors\": {}"),
            fixture.replace("\"devices\": []", "\"devices\": {}")
        )
        for (json in invalid) {
            assertThrows(Exception::class.java) { DeviceStatusCodec.decode(json) }
        }
    }

    @Test
    fun rejectsEmptyRequiredDeviceAndErrorFields() {
        for (json in listOf(
            native.replace("\"native-1\"", "\"\""),
            native.replace("\"ready\"", "\"\""),
            native.replace("\"E1\"", "\"\""),
            native.replace("\"example\"", "\"\"")
        )) {
            assertThrows(Exception::class.java) { DeviceStatusCodec.decode(json) }
        }
    }
}

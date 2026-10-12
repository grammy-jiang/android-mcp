package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

/** JVM proof of the actual Android APK's NativeLocalStatus payload producer. */
class NativeStatusGoldenTest {
    private val expected = Json.parseToJsonElement(
        """
        {
          "schema_version": 1,
          "runtime": "android",
          "capabilities": {
            "android.native.loopback_status": true,
            "android.accessibility.observe": false,
            "android.accessibility.act": false,
            "android.privileged": false
          },
          "devices": [],
          "errors": []
        }
        """.trimIndent()
    )

    @Test
    fun nativeStatusExactlyMatchesPublicV1Golden() {
        val wire = NativeLocalStatus.encode()
        assertEquals(expected, Json.parseToJsonElement(wire))
        val root = Json.parseToJsonElement(wire).jsonObject
        assertEquals(setOf("schema_version", "runtime", "capabilities", "devices", "errors"), root.keys)
        assertEquals(emptyList<Any>(), root.getValue("devices").jsonArray.toList())
        assertEquals(emptyList<Any>(), root.getValue("errors").jsonArray.toList())
        val caps = root.getValue("capabilities").jsonObject
        assertEquals(4, caps.size)
        assertFalse(caps.getValue("android.accessibility.observe").jsonPrimitive.boolean)
        assertFalse(caps.getValue("android.accessibility.act").jsonPrimitive.boolean)
        assertFalse(caps.getValue("android.privileged").jsonPrimitive.boolean)
    }

    @Test
    fun inMemoryMutantCannotPassExactV1GoldenOrSharedCodec() {
        val value = Json.parseToJsonElement(NativeLocalStatus.encode()).jsonObject
        val caps = JsonObject(
            value.getValue("capabilities").jsonObject + ("android.synthetic.secret" to
                kotlinx.serialization.json.JsonPrimitive(false))
        )
        val mutated = JsonObject(value + ("capabilities" to caps))
        assertFalse(expected == mutated)
        // The shared v1 decoder is deliberately extensible for Host capabilities;
        // the Native-specific golden assertion above is deliberately stricter.
        assertEquals(5, DeviceStatusCodec.decode(mutated.toString()).capabilities.size)
        val invalid = """{"schema_version":1,"runtime":"android","capabilities":{},"devices":[{"device_id":1}],"errors":[]}"""
        assertThrows(IllegalArgumentException::class.java) {
            DeviceStatusCodec.decode(invalid)
        }
    }
}

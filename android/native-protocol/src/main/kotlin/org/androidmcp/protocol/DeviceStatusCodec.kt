package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The JVM contract boundary: validate types instead of coercing JSON numbers
 * and booleans into strings. This remains independent of Android permissions
 * and must not be used as a substitute for authentication.
 */
data class DeviceInfo(val deviceId: String, val state: String, val properties: Map<String, String>)

data class DeviceStatus(
    val version: Int,
    val runtime: String,
    val capabilities: Map<String, Boolean>,
    val devices: List<DeviceInfo>,
    val errors: List<StatusError>,
)

data class StatusError(val code: String, val message: String)

object DeviceStatusCodec {
    private const val MAX_MESSAGE_BYTES = 128 * 1024
    private val rootFields = setOf(
        "schema_version", "runtime", "capabilities", "devices", "errors", "host", "adb"
    )
    private val deviceFields = setOf("device_id", "state", "properties")
    private val errorFields = setOf("code", "message")

    fun decode(json: String): DeviceStatus {
        require(json.toByteArray(Charsets.UTF_8).size <= MAX_MESSAGE_BYTES) {
            "Status payload exceeds budget"
        }
        val root = Json.parseToJsonElement(json).jsonObject
        root.requireOnly(rootFields)
        val version = root.getValue("schema_version").requireStrictInt()
        require(version == 1) { "Unsupported status contract version" }
        val runtime = root.requireString("runtime")
        require(runtime == "host" || runtime == "android") { "Unsupported runtime" }

        val capabilities = root.requireObject("capabilities").mapValues { (_, value) ->
            value.requireStrictBoolean()
        }
        val devices = root.getValue("devices").jsonArray.map { item ->
            val details = item.jsonObject
            details.requireOnly(deviceFields)
            val id = details.requireString("device_id", nonempty = true)
            val state = details.requireString("state", nonempty = true)
            val properties = details.requireObject("properties").mapValues { (_, value) ->
                value.requireStrictString()
            }
            DeviceInfo(id, state, properties)
        }
        val errors = root.getValue("errors").jsonArray.map { item ->
            val entry = item.jsonObject
            entry.requireOnly(errorFields)
            StatusError(
                entry.requireString("code", nonempty = true),
                entry.requireString("message", nonempty = true)
            )
        }

        if (runtime == "host") {
            require(root.containsKey("host") && root.containsKey("adb")) {
                "Host status requires platform and ADB objects"
            }
        }
        root["host"]?.let { validateHost(it.jsonObject) }
        root["adb"]?.let { validateAdb(it.jsonObject) }
        return DeviceStatus(version, runtime, capabilities, devices, errors)
    }

    private fun validateHost(host: JsonObject) {
        host.requireOnly(setOf("os", "architecture", "python"))
        require(host.requireString("os") in setOf("macos", "linux", "unsupported"))
        host.requireString("architecture", nonempty = true)
        host.requireString("python", nonempty = true)
    }

    private fun validateAdb(adb: JsonObject) {
        adb.requireOnly(setOf("available", "executable", "version", "error"))
        adb.getValue("available").requireStrictBoolean()
        for (key in listOf("executable", "version")) {
            adb.getValue(key).let { value ->
                if (value != JsonNull) value.requireStrictString()
            }
        }
        adb.getValue("error").let { value ->
            if (value != JsonNull) {
                val diagnostic = value.jsonObject
                diagnostic.requireOnly(errorFields)
                diagnostic.requireString("code", nonempty = true)
                diagnostic.requireString("message", nonempty = true)
            }
        }
    }

    private fun kotlinx.serialization.json.JsonElement.requireStrictBoolean(): Boolean {
        val primitive = jsonPrimitive
        require(!primitive.isString) { "Expected JSON boolean" }
        return primitive.boolean
    }

    private fun kotlinx.serialization.json.JsonElement.requireStrictInt(): Int {
        val primitive = jsonPrimitive
        require(!primitive.isString) { "Expected JSON integer" }
        return primitive.int
    }

    private fun JsonObject.requireOnly(allowed: Set<String>) {
        require(keys.all { it in allowed }) { "Unknown status field" }
    }

    private fun JsonObject.requireObject(field: String) =
        getValue(field).jsonObject

    private fun JsonObject.requireString(field: String, nonempty: Boolean = false): String =
        getValue(field).requireStrictString(nonempty)

    private fun kotlinx.serialization.json.JsonElement.requireStrictString(
        nonempty: Boolean = false
    ): String {
        val primitive: JsonPrimitive = jsonPrimitive
        require(primitive.isString) { "Expected JSON string" }
        val value = primitive.content
        if (nonempty) require(value.isNotEmpty()) { "Empty required string" }
        return value
    }
}

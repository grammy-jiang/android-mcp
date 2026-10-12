package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Report only the local loopback status capability, not device identifiers,
 * private diagnostic data, Host pairing or ungranted Android privileges.
 */
object NativeLocalStatus {
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("runtime", "android")
        put("capabilities", buildJsonObject {
            put("android.native.loopback_status", true)
            put("android.accessibility.observe", false)
            put("android.accessibility.act", false)
            put("android.privileged", false)
        })
        put("devices", buildJsonArray {})
        put("errors", buildJsonArray {})
    }.toString()
}

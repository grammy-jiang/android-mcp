package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * A coarse, versioned Android Build snapshot. Never contains per-device
 * identifiers, ADB/USB serials, Android ID, MAC addresses or unique firmware
 * fingerprints. Internal only until an authenticated publication review.
 */
enum class NativeBuildAvailability { AVAILABLE, PARTIAL, UNSUPPORTED }

class NativeBuildSnapshot internal constructor(
    val schemaVersion: Int,
    val runtime: String,
    val availability: NativeBuildAvailability,
    val apiLevel: Int?,
    val osRelease: String?,
    val manufacturer: String?,
    val model: String?,
    val supportedAbis: List<String>,
    val appVersion: String?,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("runtime", runtime)
        put("availability", availability.name.lowercase())
        put("api_level", apiLevel?.let(::JsonPrimitive) ?: JsonNull)
        put("os_release", osRelease?.let(::JsonPrimitive) ?: JsonNull)
        put("manufacturer", manufacturer?.let(::JsonPrimitive) ?: JsonNull)
        put("model", model?.let(::JsonPrimitive) ?: JsonNull)
        put("supported_abis", buildJsonArray {
            supportedAbis.forEach { add(JsonPrimitive(it)) }
        })
        put("app_version", appVersion?.let(::JsonPrimitive) ?: JsonNull)
    }.toString()
}

/** Only Android API 30+ basic public Build fields; no sensitive platform APIs. */
object NativeBuildSnapshots {
    private const val MIN_API = 30
    private const val MAX_REASONABLE_API = 100
    private const val MAX_FIELD_CHARS = 96
    private const val MAX_ABIS = 8
    private val ABI_PATTERN = Regex("[A-Za-z0-9._-]{2,32}")
    private val SENSITIVE = listOf(
        "serial", "android_id", "device_id", "advertising_id",
        "imei", "imsi", "fingerprint", "mac_address", "private_key",
        "token", "password", "secret",
    )

    fun normalize(
        apiLevel: Int?,
        osRelease: String?,
        manufacturer: String?,
        model: String?,
        supportedAbis: List<String>?,
        appVersion: String?,
    ): NativeBuildSnapshot {
        val supported = apiLevel != null && apiLevel in MIN_API..MAX_REASONABLE_API
        if (!supported) return NativeBuildSnapshot(
            schemaVersion = 1,
            runtime = "android",
            availability = NativeBuildAvailability.UNSUPPORTED,
            apiLevel = null,
            osRelease = null,
            manufacturer = null,
            model = null,
            supportedAbis = emptyList(),
            appVersion = null,
        )

        val releaseSafe = safeText(osRelease)
        val manufacturerSafe = safeText(manufacturer)
        val modelSafe = safeText(model)
        val versionSafe = safeText(appVersion)
        val abis = supportedAbis.orEmpty().take(MAX_ABIS)
            .filter { ABI_PATTERN.matches(it) }.distinct()
        val complete = releaseSafe != null && manufacturerSafe != null &&
            modelSafe != null && versionSafe != null && abis.isNotEmpty() &&
            supportedAbis != null && supportedAbis.size == abis.size
        return NativeBuildSnapshot(
            schemaVersion = 1,
            runtime = "android",
            availability = if (complete) {
                NativeBuildAvailability.AVAILABLE
            } else {
                NativeBuildAvailability.PARTIAL
            },
            apiLevel = apiLevel,
            osRelease = releaseSafe,
            manufacturer = manufacturerSafe,
            model = modelSafe,
            supportedAbis = abis,
            appVersion = versionSafe,
        )
    }

    private fun safeText(raw: String?): String? {
        if (raw == null || raw.length > MAX_FIELD_CHARS) return null
        val text = raw.trim()
        if (text.isEmpty() || text.any { it.isSurrogate() || it.code < 0x20 || it.code == 0x7F }) {
            return null
        }
        if (SENSITIVE.any { text.contains(it, ignoreCase = true) }) return null
        return text
    }
}

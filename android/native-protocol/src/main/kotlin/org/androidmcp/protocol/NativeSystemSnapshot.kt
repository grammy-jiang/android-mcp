package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Permission-aware app-scoped telemetry, not a device-wide profiler.
 * Snapshot is internal; no HTTP route, background observer or MCP Tool.
 */
enum class NativeSystemAvailability { AVAILABLE, PARTIAL, UNAVAILABLE, UNSUPPORTED }
enum class NativeNetworkReadiness {
    VALIDATED, INTERNET_CAPABLE, OFFLINE, PERMISSION_DENIED, UNAVAILABLE
}

/**
 * Fakeable single point-in-time inputs; never contain SSID/BSSID, address,
 * location, device ID or full package state. Android adapter reads on demand.
 */
data class NativeSystemInputs(
    val apiLevel: Int?,
    val elapsedMs: Long?,
    val batteryPercent: Int?,
    val appStorageAvailableBytes: Long?,
    val appStorageTotalBytes: Long?,
    val displayWidthPx: Int?,
    val displayHeightPx: Int?,
    val network: NativeNetworkReadiness,
)

class NativeSystemSnapshot internal constructor(
    val schemaVersion: Int,
    val availability: NativeSystemAvailability,
    val apiLevel: Int?,
    val elapsedMs: Long?,
    val batteryPercent: Int?,
    val appStorageAvailableBytes: Long?,
    val appStorageTotalBytes: Long?,
    val displayWidthPx: Int?,
    val displayHeightPx: Int?,
    val network: NativeNetworkReadiness,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("runtime", "android")
        put("availability", availability.name.lowercase())
        put("api_level", apiLevel?.let(::JsonPrimitive) ?: JsonNull)
        put("sampled_elapsed_ms", elapsedMs?.let(::JsonPrimitive) ?: JsonNull)
        put("battery_percent", batteryPercent?.let(::JsonPrimitive) ?: JsonNull)
        put(
            "app_storage_available_bytes",
            appStorageAvailableBytes?.let(::JsonPrimitive) ?: JsonNull
        )
        put(
            "app_storage_total_bytes",
            appStorageTotalBytes?.let(::JsonPrimitive) ?: JsonNull
        )
        put("app_display_width_px", displayWidthPx?.let(::JsonPrimitive) ?: JsonNull)
        put("app_display_height_px", displayHeightPx?.let(::JsonPrimitive) ?: JsonNull)
        put("network_readiness", network.name.lowercase())
    }.toString()
}

/** Conservative normalization avoids plausible but fabricated OEM readings. */
object NativeSystemSnapshots {
    private const val MAX_API = 100
    private const val MAX_DISPLAY_DIMENSION = 16_384
    private const val MAX_STORAGE_BYTES = 1L shl 55

    fun normalize(input: NativeSystemInputs): NativeSystemSnapshot {
        val api = input.apiLevel
        if (api == null || api !in 30..MAX_API) {
            return NativeSystemSnapshot(
                1, NativeSystemAvailability.UNSUPPORTED,
                null, null, null, null, null, null, null,
                NativeNetworkReadiness.UNAVAILABLE,
            )
        }

        val time = input.elapsedMs?.takeIf { it >= 0 }
        val battery = input.batteryPercent?.takeIf { it in 0..100 }
        val storageGood =
            input.appStorageTotalBytes != null &&
            input.appStorageAvailableBytes != null &&
            input.appStorageTotalBytes in 1..MAX_STORAGE_BYTES &&
            input.appStorageAvailableBytes in 0..input.appStorageTotalBytes
        val available = input.appStorageAvailableBytes.takeIf { storageGood }
        val total = input.appStorageTotalBytes.takeIf { storageGood }
        val displayGood =
            input.displayWidthPx != null && input.displayHeightPx != null &&
            input.displayWidthPx in 1..MAX_DISPLAY_DIMENSION &&
            input.displayHeightPx in 1..MAX_DISPLAY_DIMENSION
        val width = input.displayWidthPx.takeIf { displayGood }
        val height = input.displayHeightPx.takeIf { displayGood }
        val networkAvailable = input.network !in setOf(
            NativeNetworkReadiness.PERMISSION_DENIED,
            NativeNetworkReadiness.UNAVAILABLE,
        )
        val hasAny = battery != null || storageGood || displayGood || networkAvailable
        val complete = time != null && battery != null && storageGood &&
            displayGood && networkAvailable
        val availability = when {
            !hasAny -> NativeSystemAvailability.UNAVAILABLE
            complete -> NativeSystemAvailability.AVAILABLE
            else -> NativeSystemAvailability.PARTIAL
        }
        return NativeSystemSnapshot(
            schemaVersion = 1,
            availability = availability,
            apiLevel = api,
            elapsedMs = time,
            batteryPercent = battery,
            appStorageAvailableBytes = available,
            appStorageTotalBytes = total,
            displayWidthPx = width,
            displayHeightPx = height,
            network = input.network,
        )
    }
}

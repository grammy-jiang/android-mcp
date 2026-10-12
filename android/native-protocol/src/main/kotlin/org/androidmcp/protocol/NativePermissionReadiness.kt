package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N0.d typed and *internal* Android permission readiness.
 *
 * This is not an authorization grant, caller identity, or public MCP Tool.
 * Each evaluation must request fresh Android OS permission state; no cache
 * from a previous Activity/FGS incarnation can imply a future grant.
 */
enum class PermissionReadiness {
    GRANTED, DENIED, UNKNOWN, NOT_APPLICABLE, UNSUPPORTED
}

enum class NativePermissionCapability(val key: String) {
    LOOPBACK("local_status"),
    NOTIFICATIONS("notification_post"),
    FOREGROUND_SERVICE("foreground_special_use"),
    ACCESSIBILITY("accessibility"),
    MEDIA_PROJECTION("media_projection"),
    PACKAGE_VISIBILITY("package_inventory"),
    DEVICE_ADMIN("device_admin"),
    PRIVILEGED("privileged"),
}

fun interface AndroidPermissionProbe {
    /** True/false = explicit Android PackageManager state; null = unknown. */
    fun granted(permission: String): Boolean?
}

data class NativePermissionSnapshot(
    val schemaVersion: Int,
    val apiLevel: Int,
    val states: Map<NativePermissionCapability, PermissionReadiness>,
) {
    fun readiness(capability: NativePermissionCapability): PermissionReadiness =
        states[capability] ?: PermissionReadiness.UNKNOWN

    fun foregroundMayStart(): Boolean =
        apiLevel >= 34 &&
            readiness(NativePermissionCapability.FOREGROUND_SERVICE) == PermissionReadiness.GRANTED &&
            readiness(NativePermissionCapability.NOTIFICATIONS) == PermissionReadiness.GRANTED &&
            readiness(NativePermissionCapability.LOOPBACK) == PermissionReadiness.GRANTED

    /**
     * Coarse, bounded policy-only internal JSON; no Android ID, serial, log,
     * installed packages, raw permission error, token or account data.
     * Never register this as a public Tool before N0.b/N6 security approval.
     */
    fun encode(): String = buildJsonObject {
        put("schema_version", schemaVersion)
        put("api_level", apiLevel)
        put("permissions", buildJsonObject {
            for (capability in NativePermissionCapability.entries) {
                put(capability.key, readiness(capability).name.lowercase())
            }
        })
    }.toString()
}

/**
 * Calls only the four already-declared N3 Manifest permissions.
 * No requestPermissions() or OS mutation; denied/unknown never means ready.
 */
class NativePermissionReadiness(
    private val apiLevel: Int,
    private val probe: AndroidPermissionProbe,
) {
    init {
        require(apiLevel >= 1) { "Android API level cannot be negative or zero" }
    }

    fun snapshot(): NativePermissionSnapshot {
        val loopback = readPermission(INTERNET)
        val notifications =
            if (apiLevel < 33) PermissionReadiness.NOT_APPLICABLE
            else readPermission(POST_NOTIFICATIONS)
        val foreground =
            if (apiLevel < 34) PermissionReadiness.UNSUPPORTED
            else combine(readPermission(FOREGROUND_SERVICE), readPermission(FOREGROUND_SPECIAL_USE))

        return NativePermissionSnapshot(
            schemaVersion = 1,
            apiLevel = apiLevel,
            states = mapOf(
                NativePermissionCapability.LOOPBACK to loopback,
                NativePermissionCapability.NOTIFICATIONS to notifications,
                NativePermissionCapability.FOREGROUND_SERVICE to foreground,
                // None of the following are declared, consented or activated.
                NativePermissionCapability.ACCESSIBILITY to PermissionReadiness.DENIED,
                NativePermissionCapability.MEDIA_PROJECTION to PermissionReadiness.DENIED,
                NativePermissionCapability.PACKAGE_VISIBILITY to PermissionReadiness.DENIED,
                NativePermissionCapability.DEVICE_ADMIN to PermissionReadiness.UNSUPPORTED,
                NativePermissionCapability.PRIVILEGED to PermissionReadiness.UNSUPPORTED,
            ),
        )
    }

    private fun readPermission(name: String): PermissionReadiness = try {
        when (probe.granted(name)) {
            true -> PermissionReadiness.GRANTED
            false -> PermissionReadiness.DENIED
            null -> PermissionReadiness.UNKNOWN
        }
    } catch (_: RuntimeException) {
        // Never echo the Android/OEM exception; it can include account data.
        PermissionReadiness.UNKNOWN
    }

    private fun combine(
        first: PermissionReadiness,
        second: PermissionReadiness,
    ): PermissionReadiness = when {
        first == PermissionReadiness.DENIED || second == PermissionReadiness.DENIED ->
            PermissionReadiness.DENIED
        first == PermissionReadiness.UNKNOWN || second == PermissionReadiness.UNKNOWN ->
            PermissionReadiness.UNKNOWN
        first == PermissionReadiness.GRANTED && second == PermissionReadiness.GRANTED ->
            PermissionReadiness.GRANTED
        else -> PermissionReadiness.UNSUPPORTED
    }

    companion object {
        const val INTERNET = "android.permission.INTERNET"
        const val FOREGROUND_SERVICE = "android.permission.FOREGROUND_SERVICE"
        const val FOREGROUND_SPECIAL_USE = "android.permission.FOREGROUND_SERVICE_SPECIAL_USE"
        const val POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"
    }
}

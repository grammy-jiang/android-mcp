package org.androidmcp.protocol

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * One explicitly targeted Android user-visible package's *public* metadata.
 * This is a private Kotlin contract; never a Tool callable by unpaired peers.
 */
enum class PackageDetailState {
    AVAILABLE, PARTIAL, NOT_VISIBLE_OR_MISSING, DISABLED, UNINSTALLED,
    WRONG_USER, UNSUPPORTED, DENIED, UNAVAILABLE
}

data class NativePackageRequest(
    val packageName: String,
    val userScope: String = "current",
)

/** Trusted input must come from a fresh, Android-filtered PackageManager read. */
data class NativePackageDetailSource(
    val packageName: String,
    val installed: Boolean,
    val enabled: Boolean,
    val versionName: String?,
    val versionCode: Long?,
    val certificateSha256: String?,
    val hasExportedActivity: Boolean?,
)

data class NativePackageDetailResult(
    val state: PackageDetailState,
    val packageName: String?,
    val versionName: String?,
    val versionCode: Long?,
    val certificateSha256: String?,
    val hasExportedActivity: Boolean?,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("availability", state.name.lowercase())
        put("scope", "current_user_visible_package")
        put("package_name", packageName?.let(::JsonPrimitive) ?: JsonNull)
        put("version_name", versionName?.let(::JsonPrimitive) ?: JsonNull)
        put("version_code", versionCode?.let(::JsonPrimitive) ?: JsonNull)
        put("certificate_sha256", certificateSha256?.let(::JsonPrimitive) ?: JsonNull)
        put("has_exported_activity", hasExportedActivity?.let(::JsonPrimitive) ?: JsonNull)
    }.toString()
}

/**
 * No Android user enumeration or cross-profile implicit lookup. A missing
 * PackageManager result is visibility-ambiguous, never evidence of uninstall.
 */
object NativePackageDetails {
    private val PACKAGE_NAME =
        Regex("[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)+")
    private val VERSION_NAME = Regex("[A-Za-z0-9._+-]{1,48}")
    private val SHA256 = Regex("[a-fA-F0-9]{64}")
    private val FORBIDDEN = listOf(
        "password", "token", "credential", "signature", "private_key", "secret", "account"
    )

    fun unavailable(): NativePackageDetailResult = NativePackageDetailResult(
        PackageDetailState.UNAVAILABLE, null, null, null, null, null
    )

    fun validPackageName(name: String): Boolean =
        name.length in 3..160 &&
            PACKAGE_NAME.matches(name) &&
            FORBIDDEN.none { name.contains(it, ignoreCase = true) }

    fun resolve(
        apiLevel: Int,
        request: NativePackageRequest,
        visibility: NativePackageVisibilitySnapshot,
        raw: NativePackageDetailSource?,
    ): NativePackageDetailResult {
        fun noData(reason: PackageDetailState): NativePackageDetailResult =
            NativePackageDetailResult(reason, null, null, null, null, null)

        if (apiLevel !in 30..100) return noData(PackageDetailState.UNSUPPORTED)
        if (request.userScope != "current") return noData(PackageDetailState.WRONG_USER)
        if (!validPackageName(request.packageName)) return noData(PackageDetailState.DENIED)
        if (visibility.state in listOf(
                PackageVisibilityState.DENIED,
                PackageVisibilityState.UNSUPPORTED,
                PackageVisibilityState.UNAVAILABLE,
            )
        ) return noData(PackageDetailState.DENIED)
        if (visibility.lookup(request.packageName) != VisiblePackageLookup.VISIBLE) {
            return noData(PackageDetailState.NOT_VISIBLE_OR_MISSING)
        }
        if (raw == null) return noData(PackageDetailState.NOT_VISIBLE_OR_MISSING)
        if (raw.packageName != request.packageName) return noData(PackageDetailState.DENIED)
        if (!raw.installed) return noData(PackageDetailState.UNINSTALLED)
        if (!raw.enabled) return noData(PackageDetailState.DISABLED)
        val version = raw.versionName?.takeIf { text ->
            VERSION_NAME.matches(text) && FORBIDDEN.none { text.contains(it, ignoreCase = true) }
        }

        val code = raw.versionCode?.takeIf { it in 0..1_000_000_000_000L }
        val digest = raw.certificateSha256?.takeIf { SHA256.matches(it) }?.lowercase()
        val full = version != null && code != null && digest != null &&
            raw.hasExportedActivity != null
        return NativePackageDetailResult(
            state = if (full) PackageDetailState.AVAILABLE else PackageDetailState.PARTIAL,
            packageName = request.packageName,
            versionName = version,
            versionCode = code,
            certificateSha256 = digest,
            hasExportedActivity = raw.hasExportedActivity,
        )
    }
}

package org.androidmcp.protocol

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N5.d fake, read-only Host/Native health reconciliation.
 *
 * No ADB transport, Host connection, pairing, shell command, Android service
 * or automatic failover is performed here. Caller-provided "signed" flags
 * are synthetic unit-test fixtures, NOT real cryptographic verification.
 */
enum class FallbackAvailability {
    AVAILABLE, OFFLINE, UNKNOWN, STALE, DENIED,
}
enum class FallbackDecision {
    HOST_READ_ONLY, NATIVE_READ_ONLY, BOTH_AVAILABLE, UNAVAILABLE,
    UNKNOWN, STALE_BINDING, DENIED,
}
enum class FallbackProvider { HOST_ADB, NATIVE_LOOPBACK }
enum class FallbackAction {
    HOST_ADB_OBSERVE, NATIVE_STATUS, INSTALL_APK, ROOT, UI_WRITE,
    ACCESSIBILITY, REBOOT, UNKNOWN,
}
enum class FallbackCall {
    SUGGEST_READ_ONLY, DENIED, UNSUPPORTED, UNAVAILABLE,
}

/** Mocked Host evidence; ADB serial is only a transport hint, not identity. */
data class FakeHostProbe(
    val hostKey: String,
    val bootEpoch: String,
    val serial: String,
    val online: Boolean?,
    val transportVerified: Boolean,
    val signedIdentityVerified: Boolean,
    val observedAtElapsedMs: Long,
)

/** Mocked Native evidence; user-started loopback is status-only. */
data class FakeNativeProbe(
    val installationId: String,
    val bootEpoch: String,
    val userStarted: Boolean,
    val loopbackListening: Boolean,
    val appForeground: Boolean,
    val observedAtElapsedMs: Long,
)

/** An inert binding, not a live Host/Native signing key or lease. */
data class FakeHostNativeBinding(
    val expectedHostKey: String,
    val expectedHostBootEpoch: String,
    val expectedSerial: String,
    val expectedNativeInstallationId: String,
    val expectedNativeBootEpoch: String,
    val expiryElapsedMs: Long,
    val writeLeaseActive: Boolean = false,
)

data class NativeHostFallbackPlan(
    val decision: FallbackDecision,
    val host: FallbackAvailability,
    val native: FallbackAvailability,
    val providers: List<FallbackProvider>,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("decision", decision.name.lowercase())
        put("host_availability", host.name.lowercase())
        put("native_availability", native.name.lowercase())
        put("providers", buildJsonArray {
            providers.forEach { add(JsonPrimitive(it.name.lowercase())) }
        })
        put("automatic_failover", false)
        put("read_only", true)
        put("synthetic_only", true)
        put("write_capability_enabled", false)
    }.toString()
}

/**
 * Default deny and preserve provenance of both independent read-only
 * providers. Inconsistent binding, serial reuse, signer's failure, boot epoch
 * change or stale observation never permits a Host write-route fallback.
 */
object NativeHostFallback {
    private const val MAX_PROBE_AGE_MS = 5_000L
    private val PROBE_ID = Regex("[A-Za-z0-9._:-]{4,128}")
    private val SERIAL = Regex("[A-Za-z0-9._:-]{4,128}")

    fun evaluate(
        host: FakeHostProbe?,
        native: FakeNativeProbe?,
        binding: FakeHostNativeBinding?,
        nowElapsedMs: Long,
    ): NativeHostFallbackPlan {
        fun denied(decision: FallbackDecision, state: FallbackAvailability) =
            NativeHostFallbackPlan(decision, state, state, emptyList())

        if (binding == null || nowElapsedMs < 0 ||
            !PROBE_ID.matches(binding.expectedHostKey) ||
            !PROBE_ID.matches(binding.expectedHostBootEpoch) ||
            !SERIAL.matches(binding.expectedSerial) ||
            !PROBE_ID.matches(binding.expectedNativeInstallationId) ||
            !PROBE_ID.matches(binding.expectedNativeBootEpoch)
        ) return denied(FallbackDecision.DENIED, FallbackAvailability.DENIED)
        if (binding.expiryElapsedMs < nowElapsedMs) {
            return denied(FallbackDecision.STALE_BINDING, FallbackAvailability.STALE)
        }

        if (host != null && (
                host.hostKey != binding.expectedHostKey ||
                host.bootEpoch != binding.expectedHostBootEpoch ||
                host.serial != binding.expectedSerial ||
                (host.online == true &&
                    (!host.signedIdentityVerified || !host.transportVerified))
            )
        ) return denied(FallbackDecision.STALE_BINDING, FallbackAvailability.STALE)
        if (native != null && (
                native.installationId != binding.expectedNativeInstallationId ||
                native.bootEpoch != binding.expectedNativeBootEpoch
            )
        ) return denied(FallbackDecision.STALE_BINDING, FallbackAvailability.STALE)

        fun current(time: Long): Boolean =
            time >= 0 && time <= nowElapsedMs &&
                nowElapsedMs - time <= MAX_PROBE_AGE_MS

        val hostState = when {
            host == null || host.online == null -> FallbackAvailability.UNKNOWN
            host.online == false -> FallbackAvailability.OFFLINE
            !current(host.observedAtElapsedMs) -> FallbackAvailability.STALE
            else -> FallbackAvailability.AVAILABLE
        }
        val nativeState = when {
            native == null -> FallbackAvailability.UNKNOWN
            !native.userStarted || !native.loopbackListening || !native.appForeground ->
                FallbackAvailability.OFFLINE
            !current(native.observedAtElapsedMs) -> FallbackAvailability.STALE
            else -> FallbackAvailability.AVAILABLE
        }
        val choices = buildList {
            if (hostState == FallbackAvailability.AVAILABLE) add(FallbackProvider.HOST_ADB)
            if (nativeState == FallbackAvailability.AVAILABLE) {
                add(FallbackProvider.NATIVE_LOOPBACK)
            }
        }
        val decision = when {
            choices.size == 2 -> FallbackDecision.BOTH_AVAILABLE
            choices == listOf(FallbackProvider.HOST_ADB) -> FallbackDecision.HOST_READ_ONLY
            choices == listOf(FallbackProvider.NATIVE_LOOPBACK) -> FallbackDecision.NATIVE_READ_ONLY
            hostState == FallbackAvailability.UNKNOWN ||
                nativeState == FallbackAvailability.UNKNOWN -> FallbackDecision.UNKNOWN
            else -> FallbackDecision.UNAVAILABLE
        }
        return NativeHostFallbackPlan(decision, hostState, nativeState, choices)
    }

    /**
     * This is a suggestion, not an invocation. Even a synthetic "lease"
     * cannot enable mutating Host or Native routes.
     */
    fun planCall(action: FallbackAction, plan: NativeHostFallbackPlan): FallbackCall =
        when (action) {
            FallbackAction.UNKNOWN -> FallbackCall.UNSUPPORTED
            FallbackAction.INSTALL_APK, FallbackAction.ROOT,
            FallbackAction.UI_WRITE, FallbackAction.ACCESSIBILITY,
            FallbackAction.REBOOT -> FallbackCall.DENIED
            FallbackAction.HOST_ADB_OBSERVE ->
                if (FallbackProvider.HOST_ADB in plan.providers) FallbackCall.SUGGEST_READ_ONLY
                else FallbackCall.UNAVAILABLE
            FallbackAction.NATIVE_STATUS ->
                if (FallbackProvider.NATIVE_LOOPBACK in plan.providers) {
                    FallbackCall.SUGGEST_READ_ONLY
                } else FallbackCall.UNAVAILABLE
        }
}

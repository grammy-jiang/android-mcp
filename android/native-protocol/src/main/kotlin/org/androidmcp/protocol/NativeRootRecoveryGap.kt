package org.androidmcp.protocol

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N8.b — ordinary APK cannot root, flash, unlock bootloaders or repair an
 * unbootable Android OS. This is a completely inert Host fallback *plan*.
 */
enum class RootRecoverySurface {
    ROOT, BOOTLOADER, ROM_FLASH, RAW_SHELL, UNLOCK_BOOTLOADER,
    ERASE_USER_DATA, LOCKSCREEN_BYPASS, HOST_SAFE_TRIAGE, HOST_SAFE_RECOVERY_GUIDANCE,
}
enum class RootRecoveryState {
    UNSUPPORTED, DENIED, UNAVAILABLE, BLOCKED, PLAN_ONLY, REPLAY_DENIED, STOPPED,
}

/**
 * Fake environment hints, NOT signed Host trust or hardware authorization.
 * No model-controlled flag can grant a root/recovery/partition capability.
 */
data class SyntheticRootRecoveryEnvironment(
    val apiLevel: Int = 36,
    val nativeBootable: Boolean = true,
    val nativeServiceOnline: Boolean = true,
    val hostId: String = "host-verified",
    val hostIdentityVerified: Boolean = true,
    val adbAuthorized: Boolean = true,
    val fastbootAuthorized: Boolean = true,
    val physicalOwnerPresent: Boolean = true,
    val ownerConfirmed: Boolean = true,
    val modelApproved: Boolean = true,
) {
    override fun toString() = "SyntheticRootRecoveryEnvironment([REDACTED])"
}

data class SyntheticRootRecoveryRequest(
    val surface: RootRecoverySurface,
    val requestId: String = "request-safe-triage",
    val requestedCommand: String? = null,
    val bypassSecurity: Boolean = false,
) {
    override fun toString() = "SyntheticRootRecoveryRequest([REDACTED])"
}

data class RootRecoveryReceipt(
    val status: RootRecoveryState,
    val manualHostFallbackRequired: Boolean = false,
    val requiresPhysicalOwnerConfirmation: Boolean = false,
    val safeNextSteps: List<String> = emptyList(),
) {
    // Hard-coded to prevent even synthetic callers claiming a real mutation.
    val operationExecuted: Boolean = false

    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("manual_host_fallback_required", manualHostFallbackRequired)
        put("requires_physical_owner_confirmation", requiresPhysicalOwnerConfirmation)
        put("host_supervised_only", true)
        put("operation_executed", false)
        put("automatic_retry", false)
        put("synthetic_only", true)
        put("safe_next_steps", buildJsonArray {
            safeNextSteps.forEach { add(JsonPrimitive(it)) }
        })
    }.toString()
}

/**
 * Plan-only gap map. No bridge to ADB/Fastboot, shell commands, root binaries,
 * Android privileged services, real Host lease or any device-writing Tool.
 */
class NativeRootRecoveryGap {
    private var stopped = false
    private val seenRequests = HashSet<String>()

    fun inspectOrdinaryAppCapabilities(): Map<RootRecoverySurface, RootRecoveryState> =
        listOf(
            RootRecoverySurface.ROOT, RootRecoverySurface.BOOTLOADER,
            RootRecoverySurface.ROM_FLASH,
        ).associateWith { RootRecoveryState.UNSUPPORTED }

    @Synchronized
    fun evaluate(
        environment: SyntheticRootRecoveryEnvironment,
        request: SyntheticRootRecoveryRequest,
    ): RootRecoveryReceipt {
        fun denied(status: RootRecoveryState) = RootRecoveryReceipt(status)
        if (stopped) return denied(RootRecoveryState.STOPPED)
        if (request.requestedCommand != null || request.bypassSecurity) {
            return denied(RootRecoveryState.DENIED)
        }
        if (environment.apiLevel !in ANDROID_APIS) {
            return denied(RootRecoveryState.UNSUPPORTED)
        }
        when (request.surface) {
            RootRecoverySurface.ROOT, RootRecoverySurface.BOOTLOADER,
            RootRecoverySurface.ROM_FLASH -> return denied(RootRecoveryState.UNSUPPORTED)
            RootRecoverySurface.RAW_SHELL, RootRecoverySurface.UNLOCK_BOOTLOADER,
            RootRecoverySurface.ERASE_USER_DATA, RootRecoverySurface.LOCKSCREEN_BYPASS ->
                return denied(RootRecoveryState.DENIED)
            RootRecoverySurface.HOST_SAFE_TRIAGE,
            RootRecoverySurface.HOST_SAFE_RECOVERY_GUIDANCE -> Unit
        }
        if (!environment.nativeBootable || !environment.nativeServiceOnline) {
            // This is an explanatory fixture, NOT a response an unbootable
            // Native service could actually send on a network connection.
            return RootRecoveryReceipt(
                RootRecoveryState.UNAVAILABLE,
                manualHostFallbackRequired = true,
                requiresPhysicalOwnerConfirmation = true,
            )
        }
        if (!HOST_ID.matches(environment.hostId) ||
            !environment.hostIdentityVerified ||
            !environment.physicalOwnerPresent || !environment.ownerConfirmed ||
            (request.surface == RootRecoverySurface.HOST_SAFE_TRIAGE &&
                !environment.adbAuthorized) ||
            (request.surface == RootRecoverySurface.HOST_SAFE_RECOVERY_GUIDANCE &&
                !environment.fastbootAuthorized)
        ) return denied(RootRecoveryState.BLOCKED)
        if (!REQUEST_ID.matches(request.requestId)) return denied(RootRecoveryState.DENIED)
        if (request.requestId in seenRequests) return denied(RootRecoveryState.REPLAY_DENIED)
        if (seenRequests.size >= MAX_REQUESTS) return denied(RootRecoveryState.BLOCKED)
        seenRequests.add(request.requestId)
        return RootRecoveryReceipt(
            RootRecoveryState.PLAN_ONLY,
            manualHostFallbackRequired = true,
            requiresPhysicalOwnerConfirmation = true,
            safeNextSteps = SAFE_MANUAL_STEPS,
        )
    }

    @Synchronized
    fun stop() {
        stopped = true
    }

    fun realRootOrFlashAllowed(): Boolean = false

    companion object {
        private const val MAX_REQUESTS = 32
        private val ANDROID_APIS = setOf(30, 33, 34, 36)
        private val HOST_ID = Regex("[A-Za-z0-9_-]{8,128}")
        private val REQUEST_ID = Regex("[A-Za-z0-9_-]{1,128}")
        private val SAFE_MANUAL_STEPS = listOf(
            "Confirm physical device ownership and obtain informed owner approval",
            "Use a separately authenticated Host for read-only device diagnosis",
            "Consult official manufacturer recovery guidance; authorize any future action separately",
        )
    }
}

package org.androidmcp.protocol

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N8.a read-only feasibility policy. Neither fake DeviceOwner claims nor
 * Android's own-app status probe enable a policy change or provisioning.
 */
enum class ManagedPolicyState { UNSUPPORTED, PLAN_ONLY, DENIED, REVOKED, UNAVAILABLE }
enum class ManagedPolicyOperation {
    INSPECT_MANAGED_FEATURES, MODIFY_POLICY, WIPE_DEVICE, LOCK_DEVICE,
    CHANGE_ACCOUNT, SILENT_INSTALL, SELF_PROVISION,
}

/**
 * All fields are injected test observations, NOT Android device-admin grants.
 * A model-controlled role string is diagnostic noise, never an authorization.
 */
data class FakeManagedDeviceEnvironment(
    val apiLevel: Int = 36,
    val ownDeviceOwnerVerified: Boolean? = null,
    val declaredAdminReceiver: Boolean = false,
    val ownedDisposableDevice: Boolean = false,
    val fakeUserConfirmed: Boolean = false,
    val fakeCallerVerified: Boolean = false,
    val modelRoleClaim: String = "",
) {
    override fun toString() = "FakeManagedDeviceEnvironment([REDACTED])"
}

data class ManagedPolicyReceipt(
    val status: ManagedPolicyState,
    val features: List<String> = emptyList(),
) {
    val planOnly: Boolean = status == ManagedPolicyState.PLAN_ONLY
    val sideEffectsPerformed: Boolean = false

    /** Fixed public-safe metadata, no user/tenant/admin/device identifiers. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("features", buildJsonArray { features.forEach { add(JsonPrimitive(it)) } })
        put("plan_only", planOnly)
        put("mutation_allowed", false)
        put("side_effects_performed", false)
        put("synthetic_only", true)
        put("requires_independent_review", true)
    }.toString()
}

/**
 * No admin receiver, DevicePolicyManager mutation or OS provisioning path.
 * Synthetic own-DeviceOwner=true only lists hypothetical policy capabilities.
 */
class NativeManagedDevicePolicy {
    private var revoked = false

    @Synchronized
    fun inspect(env: FakeManagedDeviceEnvironment): ManagedPolicyReceipt {
        fun denied(code: ManagedPolicyState) = ManagedPolicyReceipt(code)
        if (revoked) return denied(ManagedPolicyState.REVOKED)
        if (env.apiLevel !in SUPPORTED_APIS) return denied(ManagedPolicyState.UNSUPPORTED)
        if (env.ownDeviceOwnerVerified != true) {
            return denied(
                if (env.ownDeviceOwnerVerified == null && env.declaredAdminReceiver &&
                    env.ownedDisposableDevice
                ) ManagedPolicyState.UNAVAILABLE else ManagedPolicyState.UNSUPPORTED,
            )
        }
        if (!env.declaredAdminReceiver || !env.ownedDisposableDevice ||
            !env.fakeUserConfirmed || !env.fakeCallerVerified
        ) return denied(ManagedPolicyState.UNSUPPORTED)
        // These names are *planning references* only, not supported by our
        // ordinary non-admin production APK and not callable operations.
        return ManagedPolicyReceipt(ManagedPolicyState.PLAN_ONLY, PLAN_NAMES)
    }

    /** All DevicePolicyManager mutations remain prohibited, even for fake owner. */
    @Suppress("UNUSED_PARAMETER")
    @Synchronized
    fun evaluate(env: FakeManagedDeviceEnvironment, operation: ManagedPolicyOperation): ManagedPolicyReceipt =
        if (operation == ManagedPolicyOperation.INSPECT_MANAGED_FEATURES) {
            inspect(env)
        } else {
            ManagedPolicyReceipt(ManagedPolicyState.DENIED)
        }

    @Synchronized
    fun revoke() {
        revoked = true
    }

    fun realPolicyMutationAllowed(): Boolean = false

    companion object {
        private val SUPPORTED_APIS = setOf(30, 33, 34, 36)
        private val PLAN_NAMES = listOf("policy_audit", "lock_task", "app_restrictions")
    }
}

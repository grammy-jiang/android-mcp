package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/**
 * N6.e — internal, permanently inert and non-executable sensitive Tool model.
 * This is never connected to LocalMcpGateway, Android UI services, package
 * installation, system settings, or a real Host/Native pairing record.
 */
enum class NativeMutationOperation { UI_GESTURE, APK_INSTALL, SYSTEM_SETTING, SCREEN_CAPTURE }
enum class NativeMutationStatus {
    DISABLED, UNAUTHENTICATED, STALE, CONSENT_REQUIRED, REPLAY_DENIED,
    UNCERTAIN, STOPPED, UNSUPPORTED, DENIED,
}

data class DisabledMutationDescriptor(
    val operation: NativeMutationOperation,
    val potentiallyDestructive: Boolean = true,
) {
    // Non-overridable hard-disabled metadata, not a caller-selected profile.
    val enabled: Boolean = false
    val readOnly: Boolean = false
    val idempotent: Boolean = false
    /** Internal metadata cannot be passed as an actual MCP Tool descriptor. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("operation", operation.name.lowercase())
        put("enabled", false)
        put("read_only", false)
        put("idempotent", false)
        put("potentially_destructive", potentiallyDestructive)
        put("sensitive", true)
        put("requires_verified_user_consent", true)
        put("requires_independent_security_review", true)
        put("synthetic_only", true)
        put("executable", false)
    }.toString()
}

/** Fake inputs MUST NOT be deserialized from HTTP, Intents, or model output. */
data class SyntheticMutationAttempt(
    val operation: NativeMutationOperation,
    val processEpoch: String,
    val requestId: String,
    val actionDigest: String,
    val modelApproved: Boolean = false,
    val fakeCallerVerified: Boolean = false,
    val fakeSignedActionFresh: Boolean = false,
    val fakeLeasePresent: Boolean = false,
    val fakeRuntimeConsent: Boolean = false,
    val schemaVersion: Int = 1,
) {
    override fun toString() = "SyntheticMutationAttempt([REDACTED])"
}

/** Injected test fixture, not durable or authenticated Android state. */
data class MutationDenyRecovery(val ambiguousDigests: List<String>) {
    override fun toString() = "MutationDenyRecovery([REDACTED])"
}

data class MutationDenyReceipt(val status: NativeMutationStatus) {
    // A receipt cannot be constructed with a misleading executed=true flag.
    val mutationExecuted: Boolean = false
    /** A fixed, bounded diagnostic with no action, device, Host or token IDs. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("mutation_executed", false)
        put("automatic_retry", false)
        put("production_profile_enabled", false)
        put("requires_real_android_consent", true)
    }.toString()
}

/**
 * The permit fields below are **fake**. Passing all of them only reaches a
 * disabled terminal state, never an authorization. Synthetic ambiguity is
 * recorded before returning a fake uncertain result; replays are denied even
 * when request IDs/epochs rotate, with a bounded fail-closed fixture ledger.
 */
class NativeMutationPolicy(recovery: MutationDenyRecovery? = null) {
    val processEpoch: String = UUID.randomUUID().toString()
    private var stopped = false
    private val invalidRecovery = recovery != null &&
        (recovery.ambiguousDigests.size > MAX_AMBIGUOUS ||
            recovery.ambiguousDigests.any { !DIGEST.matches(it) } ||
            recovery.ambiguousDigests.size != recovery.ambiguousDigests.toSet().size)
    private val ambiguousDigests = LinkedHashSet<String>().apply {
        if (!invalidRecovery) recovery?.ambiguousDigests?.let(::addAll)
    }

    /** Descriptive local fixture only; the actual tools/list never uses it. */
    fun privateDescriptors(): List<DisabledMutationDescriptor> =
        NativeMutationOperation.entries.map { operation ->
            DisabledMutationDescriptor(
                operation = operation,
                potentiallyDestructive = operation != NativeMutationOperation.SCREEN_CAPTURE,
            )
        }

    fun publicMutatingTools(): List<String> = emptyList()

    @Synchronized
    fun evaluate(request: SyntheticMutationAttempt): MutationDenyReceipt {
        fun denied(code: NativeMutationStatus) = MutationDenyReceipt(code)
        if (stopped) return denied(NativeMutationStatus.STOPPED)
        if (invalidRecovery) return denied(NativeMutationStatus.UNCERTAIN)
        if (request.schemaVersion != 1) return denied(NativeMutationStatus.UNSUPPORTED)
        if (!REQUEST_ID.matches(request.requestId) ||
            !DIGEST.matches(request.actionDigest)
        ) return denied(NativeMutationStatus.DENIED)
        if (request.processEpoch != processEpoch) return denied(NativeMutationStatus.STALE)
        if (!request.fakeCallerVerified || !request.fakeSignedActionFresh ||
            !request.fakeLeasePresent
        ) return denied(NativeMutationStatus.UNAUTHENTICATED)
        if (request.actionDigest in ambiguousDigests) {
            return denied(NativeMutationStatus.UNCERTAIN)
        }
        if (!request.fakeRuntimeConsent) return denied(NativeMutationStatus.CONSENT_REQUIRED)
        // Even all-positive fake fields, including modelApproved=true, cannot
        // substitute for a real OS permission, user decision, and external review.
        return denied(NativeMutationStatus.DISABLED)
    }

    @Synchronized
    fun markFakeAmbiguous(request: SyntheticMutationAttempt): MutationDenyReceipt {
        val preliminary = evaluate(request)
        if (preliminary.status != NativeMutationStatus.DISABLED) return preliminary
        if (ambiguousDigests.size >= MAX_AMBIGUOUS) {
            return MutationDenyReceipt(NativeMutationStatus.DENIED)
        }
        ambiguousDigests.add(request.actionDigest)
        // This simulates a post-dispatch uncertain receipt. No Android action
        // was dispatched, and the ledger is a local test fixture only.
        return MutationDenyReceipt(NativeMutationStatus.UNCERTAIN)
    }

    @Synchronized
    fun snapshot(): MutationDenyRecovery =
        MutationDenyRecovery(ambiguousDigests.toList())

    @Synchronized
    fun stop() {
        stopped = true
    }

    /** Never an Android capability, even under a synthetic lease. */
    fun realMutationAllowed(): Boolean = false

    companion object {
        private const val MAX_AMBIGUOUS = 32
        private val DIGEST = Regex("[a-f0-9]{64}")
        private val REQUEST_ID = Regex("[A-Za-z0-9_-]{1,128}")
    }
}

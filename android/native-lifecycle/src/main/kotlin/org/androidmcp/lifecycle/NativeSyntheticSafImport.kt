package org.androidmcp.lifecycle

import java.security.MessageDigest
import java.util.UUID
import org.androidmcp.protocol.NativeSafGrantPolicy
import org.androidmcp.protocol.SafAccessMode
import org.androidmcp.protocol.SafGrantStatus

/**
 * N4.e: READ-ONLY synthetic import *plan*. No ContentResolver writes,
 * streams, user files, PackageManager mutations or public MCP handlers.
 */
enum class SafImportState {
    PLAN_ONLY, DENIED, REVOKED, EXPIRED, STALE, MISSING_ARTIFACT,
    HASH_MISMATCH, OVERSIZE, WRONG_PROVIDER, CANCELLED, UNCERTAIN,
    REPLAY_DENIED, UNAVAILABLE,
}

data class SyntheticSafImportRequest(
    val grantHandle: String,
    val destinationUri: String,
    val artifactHandle: String,
    val expectedSha256: String,
    val providerAuthority: String,
    val providerProcessId: String,
    val idempotencyKey: String,
    val fakeCallerAuthenticated: Boolean = true,
    val fakeUserApproved: Boolean = true,
) {
    override fun toString(): String = "SyntheticSafImportRequest([REDACTED])"
}

data class SyntheticSafImportPlan(
    val state: SafImportState,
    val planId: String?,
    val bytesToWrite: Int?,
    val sha256: String?,
) {
    fun encode(): String =
        "{\"schema_version\":1,\"status\":\"" + state.name.lowercase() +
            "\",\"synthetic_only\":true,\"executed\":false," +
            "\"atomic_write_guaranteed\":false,\"requires_fresh_user_consent\":true}"

    override fun toString(): String = "SyntheticSafImportPlan(status=" +
        state.name + ", plan=[REDACTED])"
}

/**
 * A fake WRITE grant for exactly one selected destination and an N0.e
 * private, hash-validated artifact can produce a deterministic import plan.
 *
 * It is not an authorization credential and cannot write ContentProviders.
 * No plan persists through process death, provider cancellation or a lease
 * change. A fake post-dispatch cancellation is UNCERTAIN, never atomic.
 */
class NativeSyntheticSafImportPlanner(
    private val artifacts: NativeArtifactStore,
    private val grants: NativeSafGrantPolicy,
    private val expectedAuthority: String,
    private val expectedProviderProcessId: String,
) {
    val epoch: String = UUID.randomUUID().toString()
    private var cancelled: SafImportState? = null
    private var fakeDispatchStarted = false
    private var memo: Pair<ByteArray, SyntheticSafImportPlan>? = null
    private var plannedGrantHandle: String? = null

    @Synchronized
    fun plan(request: SyntheticSafImportRequest): SyntheticSafImportPlan {
        fun deny(state: SafImportState): SyntheticSafImportPlan =
            SyntheticSafImportPlan(state, null, null, null)
        cancelled?.let { return deny(it) }
        if (!request.fakeCallerAuthenticated || !request.fakeUserApproved ||
            !KEY.matches(request.idempotencyKey) ||
            !HANDLE.matches(request.artifactHandle) ||
            !HASH.matches(request.expectedSha256)
        ) return deny(SafImportState.DENIED)

        val permission = grants.check(request.grantHandle, SafAccessMode.WRITE)
        when (permission) {
            SafGrantStatus.REVOKED -> return deny(SafImportState.REVOKED)
            SafGrantStatus.EXPIRED -> return deny(SafImportState.EXPIRED)
            SafGrantStatus.STALE -> return deny(SafImportState.STALE)
            SafGrantStatus.SIMULATED_ONLY -> Unit
            else -> return deny(SafImportState.DENIED)
        }
        if (!grants.matchesSelectedUri(
                request.grantHandle, request.destinationUri, SafAccessMode.WRITE,
            )
        ) return deny(SafImportState.DENIED)
        if (request.providerAuthority != expectedAuthority ||
            request.providerProcessId != expectedProviderProcessId
        ) return deny(SafImportState.WRONG_PROVIDER)

        // The N0.e store verifies private file identity, exact size and SHA
        // before returning a new copy. Neither a path nor byte-array handle
        // from a public request can bypass this storage boundary.
        val bytes = try {
            artifacts.read(request.artifactHandle)
        } catch (_: Exception) {
            null
        } ?: return deny(SafImportState.MISSING_ARTIFACT)
        try {
            if (bytes.size !in 1..MAX_BYTES) return deny(SafImportState.OVERSIZE)
            val trustedHash = sha256(bytes).joinToString("") { "%02x".format(it) }
            if (!trustedHash.equals(request.expectedSha256, ignoreCase = true)) {
                return deny(SafImportState.HASH_MISMATCH)
            }
            val keyHash = sha256(
                listOf(
                    epoch, request.grantHandle, request.destinationUri,
                    request.artifactHandle, request.expectedSha256,
                    request.idempotencyKey, request.providerProcessId,
                ).joinToString("|").toByteArray(Charsets.UTF_8)
            )
            memo?.let { (hash, previous) ->
                return if (MessageDigest.isEqual(hash, keyHash)) previous
                else deny(SafImportState.DENIED)
            }
            val planId = keyHash.joinToString("") { "%02x".format(it) }
            val result = SyntheticSafImportPlan(
                SafImportState.PLAN_ONLY, planId, bytes.size, trustedHash,
            )
            memo = keyHash to result
            plannedGrantHandle = request.grantHandle
            return result
        } finally {
            bytes.fill(0)
        }
    }

    @Synchronized
    fun markFakeDispatchStarted(): SafImportState {
        cancelled?.let { return it }
        if (memo?.second?.state != SafImportState.PLAN_ONLY) {
            return SafImportState.DENIED
        }
        val handle = plannedGrantHandle ?: return SafImportState.DENIED
        // Permission can be revoked BETWEEN plan creation and mock
        // dispatch. Never report an approved synthetic operation then.
        return when (grants.check(handle, SafAccessMode.WRITE)) {
            SafGrantStatus.SIMULATED_ONLY -> {
                fakeDispatchStarted = true
                SafImportState.PLAN_ONLY
            }
            SafGrantStatus.REVOKED -> SafImportState.REVOKED
            SafGrantStatus.EXPIRED -> SafImportState.EXPIRED
            else -> SafImportState.DENIED
        }
    }

    @Synchronized
    fun cancel(): SafImportState {
        cancelled?.let { return it }
        val result = if (fakeDispatchStarted) SafImportState.UNCERTAIN
        else SafImportState.CANCELLED
        cancelled = result
        memo = null
        plannedGrantHandle = null
        return result
    }

    fun realDocumentWriteAllowed(): Boolean = false

    companion object {
        private const val MAX_BYTES = 1024 * 1024
        private val KEY = Regex("[A-Za-z0-9_-]{1,64}")
        private val HANDLE = Regex("[A-Za-z0-9_-]{32}")
        private val HASH = Regex("[a-fA-F0-9]{64}")

        private fun sha256(data: ByteArray): ByteArray =
            MessageDigest.getInstance("SHA-256").digest(data)
    }
}

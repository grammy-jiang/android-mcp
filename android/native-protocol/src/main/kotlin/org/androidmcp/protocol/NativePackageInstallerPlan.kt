package org.androidmcp.protocol

import java.security.MessageDigest
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N7.a scoped, deterministic **plan only** for future user-mediated install.
 * This library never calls PackageInstaller, ContentResolver or an Android
 * permission API and is NOT registered as a production Native MCP Tool.
 */
enum class NativeInstallPlanStatus {
    PLAN_ONLY, DENIED, NOT_TRUSTED, UNSUPPORTED, UNAVAILABLE,
    REPLAY_DENIED, CANCELLED, STOPPED,
}

/**
 * Fake app-private artifact metadata, not a filesystem path, URI or OS grant.
 * Raw APK bytes and real signature certificates are never read by this model.
 */
data class SyntheticApkArtifact(
    val handle: String,
    val packageName: String,
    val abi: String,
    val minSdk: Int,
    val targetSdk: Int,
    val apkSha256: String,
    val signingCertSha256: String,
    val bytes: Long,
    val signed: Boolean = true,
    val privateArtifactPresent: Boolean = true,
    val sourceUri: String? = null,
) {
    override fun toString() = "SyntheticApkArtifact([REDACTED])"
}

data class SyntheticInstallPlanRequest(
    val artifact: SyntheticApkArtifact,
    val requestId: String,
    val callerVerified: Boolean = true,
    val approvedByModel: Boolean = false,
    val installWithoutPrompt: Boolean = false,
    val requestBroadInstallPermission: Boolean = false,
    val schemaVersion: Int = 1,
) {
    override fun toString() = "SyntheticInstallPlanRequest([REDACTED])"
}

/**
 * All supplied trust facts are injected test fixtures. No value here is
 * enough to establish real APK signature trust or user-granted install rights.
 */
data class NativeInstallerPlanEnvironment(
    val apiLevel: Int,
    val nativeAbi: String,
    val allowedPackages: Set<String>,
    val pinnedApkDigests: Set<String>,
    val trustedSigningCerts: Set<String>,
    val foreground: Boolean = true,
    val ownUserVisibleActivity: Boolean = true,
    val unknownSourcesAllowed: Boolean? = null,
)

data class NativeInstallPlanReceipt(
    val status: NativeInstallPlanStatus,
    val planId: String? = null,
    val requiresUserConfirmation: Boolean = false,
    val requiresUnknownSourcesSettings: Boolean = false,
) {
    /** These properties must not be model/caller-overridable. */
    val unknownSourcesGranted: Boolean = false
    val installationPerformed: Boolean = false
    val installerSessionOpened: Boolean = false

    /** No private artifact handle, raw package, app fingerprint or plan token. */
    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("synthetic_only", true)
        put("requires_user_confirmation", requiresUserConfirmation)
        put("requires_unknown_sources_settings", requiresUnknownSourcesSettings)
        put("unknown_sources_granted", false)
        put("installation_performed", false)
        put("installer_session_opened", false)
        put("automatic_retry", false)
    }.toString()
}

/**
 * Per-process local fake planner with a bounded one-use request journal.
 * Cancel and Stop are terminal; neither opens/abandons a real install session.
 */
class NativePackageInstallerPlans(private val env: NativeInstallerPlanEnvironment) {
    private val plans = LinkedHashMap<String, NativeInstallPlanStatus>()
    private val seenRequests = HashSet<String>()
    private var stopped = false

    @Synchronized
    fun plan(request: SyntheticInstallPlanRequest): NativeInstallPlanReceipt {
        fun reject(status: NativeInstallPlanStatus) = NativeInstallPlanReceipt(status)
        if (stopped) return reject(NativeInstallPlanStatus.STOPPED)
        if (env.apiLevel !in 30..36) return reject(NativeInstallPlanStatus.UNSUPPORTED)
        if (request.schemaVersion != 1 || request.installWithoutPrompt ||
            request.requestBroadInstallPermission || !request.callerVerified ||
            !env.foreground || !env.ownUserVisibleActivity ||
            !REQUEST_ID.matches(request.requestId)
        ) return reject(NativeInstallPlanStatus.DENIED)
        val item = request.artifact
        if (!HANDLE.matches(item.handle) ||
            item.sourceUri != null ||
            !NativePackageDetails.validPackageName(item.packageName) ||
            item.packageName.length > 160 || item.abi !in VALID_ABIS ||
            env.nativeAbi !in VALID_ABIS || item.abi != env.nativeAbi ||
            item.minSdk !in 30..env.apiLevel ||
            item.targetSdk !in 30..env.apiLevel ||
            item.minSdk > item.targetSdk || item.bytes !in 1..MAX_APK_BYTES ||
            !SHA256.matches(item.apkSha256) ||
            !SHA256.matches(item.signingCertSha256)
        ) return reject(NativeInstallPlanStatus.DENIED)
        if (!item.privateArtifactPresent || !item.signed ||
            item.packageName !in env.allowedPackages ||
            item.apkSha256 !in env.pinnedApkDigests ||
            item.signingCertSha256 !in env.trustedSigningCerts
        ) return reject(NativeInstallPlanStatus.NOT_TRUSTED)
        if (request.requestId in seenRequests) {
            return reject(NativeInstallPlanStatus.REPLAY_DENIED)
        }
        if (plans.size >= MAX_PLANS) return reject(NativeInstallPlanStatus.UNAVAILABLE)
        val normalized = listOf(
            "n7a-v1", item.handle, item.packageName, item.abi,
            item.minSdk.toString(), item.targetSdk.toString(),
            item.bytes.toString(), item.apkSha256, item.signingCertSha256,
            request.requestId,
        ).joinToString("|")
        // Hash is only a deterministic plan ID, never an execution credential.
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(normalized.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        if (digest in plans) return reject(NativeInstallPlanStatus.REPLAY_DENIED)
        plans[digest] = NativeInstallPlanStatus.PLAN_ONLY
        seenRequests.add(request.requestId)
        return NativeInstallPlanReceipt(
            NativeInstallPlanStatus.PLAN_ONLY, digest,
            requiresUserConfirmation = true,
            requiresUnknownSourcesSettings = env.unknownSourcesAllowed != true,
        )
    }

    @Synchronized
    fun cancel(planId: String): NativeInstallPlanStatus {
        if (stopped) return NativeInstallPlanStatus.STOPPED
        if (!SHA256.matches(planId) || planId !in plans) return NativeInstallPlanStatus.DENIED
        plans[planId] = NativeInstallPlanStatus.CANCELLED
        return NativeInstallPlanStatus.CANCELLED
    }

    @Synchronized
    fun stop() {
        stopped = true
        plans.replaceAll { _, _ -> NativeInstallPlanStatus.CANCELLED }
    }

    /** Always no sessions: this class does not import any Android install API. */
    fun activeInstallerSessions(): Int = 0
    fun realInstallerEnabled(): Boolean = false

    companion object {
        private const val MAX_PLANS = 64
        private const val MAX_APK_BYTES = 1024L * 1024L * 1024L
        private val SHA256 = Regex("[a-f0-9]{64}")
        private val HANDLE = Regex("[A-Za-z0-9_-]{32}")
        private val REQUEST_ID = Regex("[A-Za-z0-9_-]{1,128}")
        private val VALID_ABIS = setOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")
    }
}

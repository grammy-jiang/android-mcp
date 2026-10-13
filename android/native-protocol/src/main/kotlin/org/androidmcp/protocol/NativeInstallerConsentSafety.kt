package org.androidmcp.protocol

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * N7.b: test-only consent feasibility model. No actual PackageInstaller
 * Activity, Android permission request or session is available through this
 * model. Real Android-mediated consent remains explicitly **blocked**.
 */
enum class NativeInstallerConsentStatus {
    ELIGIBLE_EMULATOR_ONLY, REJECTED_TARGET, BLOCKED, REFUSED,
    CANCELLED, ABANDONED, STOPPED,
}

/** Caller-supplied emulator flags are NEVER proof of a real QEMU target. */
data class FakeInstallerEmulatorProof(
    val serial: String,
    val expectedApi: Int,
    val observedApi: Int,
    val qemuKernel: Boolean,
    val bootComplete: Boolean,
    val ownedDisposable: Boolean,
) {
    override fun toString() = "FakeInstallerEmulatorProof([REDACTED])"
}

data class FakeInstallerConsentRequest(
    val emulator: FakeInstallerEmulatorProof,
    val requestId: String,
    val signedTestArtifact: Boolean,
    val trustedTestPackage: Boolean,
    val apiUnknownSourcesAllowed: Boolean?,
    val ownActivityForeground: Boolean = true,
    val visibleOwnerGesture: Boolean = true,
    val callerVerified: Boolean = true,
    val modelApproved: Boolean = false,
) {
    override fun toString() = "FakeInstallerConsentRequest([REDACTED])"
}

data class FakeInstallerConsentReceipt(
    val status: NativeInstallerConsentStatus,
    val requiresVisibleOsConsent: Boolean = false,
    val requiresUnknownSourcesSettings: Boolean = false,
) {
    /** Non-overridable: no test can fake live PackageInstaller side effects. */
    val installed = false
    val consentUiOpened = false
    val sessionOpened = false

    fun encode(): String = buildJsonObject {
        put("schema_version", 1)
        put("status", status.name.lowercase())
        put("requires_visible_os_consent", requiresVisibleOsConsent)
        put("requires_unknown_sources_settings", requiresUnknownSourcesSettings)
        put("installed", false)
        put("consent_ui_opened", false)
        put("installer_session_opened", false)
        put("synthetic_only", true)
        put("automatic_retry", false)
    }.toString()
}

/**
 * No platform mutation possible. A positive fake preflight ONLY explains
 * where owner approval would be needed; it cannot unlock the real installer.
 * The separate Python QEMU preflight checks the real ADB properties but still
 * cannot establish disposable-AVD ownership or a signed test-APK flow.
 */
class NativeInstallerConsentSafety {
    private var stopped = false

    @Synchronized
    fun preflight(request: FakeInstallerConsentRequest): FakeInstallerConsentReceipt {
        if (stopped) return FakeInstallerConsentReceipt(NativeInstallerConsentStatus.STOPPED)
        val p = request.emulator
        if (!SERIAL.matches(p.serial) ||
            p.expectedApi !in SUPPORTED_APIS ||
            p.observedApi != p.expectedApi ||
            !p.qemuKernel || !p.bootComplete || !p.ownedDisposable ||
            !request.signedTestArtifact || !request.trustedTestPackage ||
            !request.ownActivityForeground || !request.visibleOwnerGesture ||
            !request.callerVerified || !REQUEST.matches(request.requestId)
        ) return FakeInstallerConsentReceipt(NativeInstallerConsentStatus.REJECTED_TARGET)
        return FakeInstallerConsentReceipt(
            NativeInstallerConsentStatus.ELIGIBLE_EMULATOR_ONLY,
            requiresVisibleOsConsent = true,
            requiresUnknownSourcesSettings = request.apiUnknownSourcesAllowed != true,
        )
    }

    @Synchronized
    fun attemptConsentUi(request: FakeInstallerConsentRequest): FakeInstallerConsentReceipt {
        val eligible = preflight(request)
        if (eligible.status != NativeInstallerConsentStatus.ELIGIBLE_EMULATOR_ONLY) {
            return eligible
        }
        // Intentionally NEVER invoke startActivity, PackageInstaller or grant.
        return FakeInstallerConsentReceipt(
            NativeInstallerConsentStatus.BLOCKED,
            requiresVisibleOsConsent = true,
            requiresUnknownSourcesSettings = eligible.requiresUnknownSourcesSettings,
        )
    }

    @Synchronized
    fun refuse(): FakeInstallerConsentReceipt =
        FakeInstallerConsentReceipt(NativeInstallerConsentStatus.REFUSED)

    @Synchronized
    fun cancel(): FakeInstallerConsentReceipt =
        FakeInstallerConsentReceipt(NativeInstallerConsentStatus.CANCELLED)

    @Synchronized
    fun processDeath(): FakeInstallerConsentReceipt =
        FakeInstallerConsentReceipt(NativeInstallerConsentStatus.ABANDONED)

    @Synchronized
    fun stop() {
        stopped = true
    }

    fun activeSessions(): Int = 0
    fun realInstallerEnabled(): Boolean = false

    companion object {
        private val SUPPORTED_APIS = setOf(30, 33, 34, 36)
        private val SERIAL = Regex("emulator-[0-9]{4,6}")
        private val REQUEST = Regex("[A-Za-z0-9_-]{1,128}")
    }
}

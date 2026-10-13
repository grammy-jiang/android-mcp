package org.androidmcp.nativeapp

/**
 * N7.d: no sensitive sessions exist in the status-only production Native app.
 * A process/service restart NEVER resumes fake capture, challenges or leases.
 * The existing NativeMcpForegroundService handles real verified Start/Stop.
 */
internal object AndroidServiceRecoveryBoundary {
    fun resumeCaptureAfterRestart(): Boolean = false
    fun resumeCallerChallengeAfterRestart(): Boolean = false
    fun resumeNativeLeaseAfterRestart(): Boolean = false
    fun allowImplicitServiceStart(): Boolean = false
}

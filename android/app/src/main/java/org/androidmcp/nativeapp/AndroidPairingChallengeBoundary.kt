package org.androidmcp.nativeapp

import android.content.Context
import org.androidmcp.protocol.PairingProofState

/**
 * No signed Host/Native pairing transport has been jointly admitted.
 * Fake JVM verification never authorizes production caller identity.
 * USB tunnel, Android loopback and ADB serial are not credentials.
 */
internal object AndroidPairingChallengeBoundary {
    @Suppress("UNUSED_PARAMETER")
    fun verify(context: Context, packet: ByteArray): PairingProofState =
        PairingProofState.UNAVAILABLE
}

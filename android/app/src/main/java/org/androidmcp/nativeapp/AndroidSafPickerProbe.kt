package org.androidmcp.nativeapp

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Process
import android.net.Uri
import org.androidmcp.protocol.NativeSafGrantPolicy
import org.androidmcp.protocol.SafAccessMode
import org.androidmcp.protocol.SyntheticSafPickerResult

/**
 * N4.c read-only Activity-result metadata adapter for a future owner-driven
 * ACTION_OPEN_DOCUMENT picker. No picker is launched in this work package.
 *
 * Neither an Intent flag nor a content URI string alone grants access.
 * The Android OS permission is checked for this app PID/UID, including
 * persisted permission status read-only. No takePersistableUriPermission,
 * openInputStream, openOutputStream or ContentResolver mutation is performed.
 *
 * The currently deployed APK does not call this private adapter, and
 * ownership of picker session must be proven separately by a future Activity
 * callback. A model-supplied trustedOwnedPicker boolean is NOT authorization.
 */
internal object AndroidSafPickerProbe {
    fun observe(
        context: Context,
        resultCode: Int,
        result: Intent?,
        ownPickerSessionVerified: Boolean,
        launchedPickerAction: String,
        localEpoch: String,
        nonce: String,
        requestedMode: SafAccessMode,
    ): SyntheticSafPickerResult {
        val uri: Uri? = result?.data
        val flags = result?.flags ?: 0
        val readAllowed = verifyCurrentPermission(
            context, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION,
        )
        val writeAllowed = verifyCurrentPermission(
            context, uri, Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
        )
        val persistedRead = verifyPersistedPermission(context, uri, SafAccessMode.READ)
        val persistedWrite = verifyPersistedPermission(context, uri, SafAccessMode.WRITE)
        return SyntheticSafPickerResult(
            apiLevel = Build.VERSION.SDK_INT,
            processEpoch = localEpoch,
            nonce = nonce,
            launchedFromOwnPicker = ownPickerSessionVerified,
            action = launchedPickerAction,
            resultOk = resultCode == Activity.RESULT_OK,
            contentUri = uri?.toString(),
            requestedMode = requestedMode,
            grantFlags = flags,
            osReadGranted = readAllowed,
            osWriteGranted = writeAllowed,
            osPersistedRead = persistedRead,
            osPersistedWrite = persistedWrite,
        )
    }

    private fun verifyCurrentPermission(
        context: Context,
        uri: Uri?,
        flag: Int,
    ): Boolean? {
        if (uri == null || uri.scheme != "content") return false
        return try {
            context.checkUriPermission(
                uri, Process.myPid(), Process.myUid(), flag,
            ) == PackageManager.PERMISSION_GRANTED
        } catch (_: RuntimeException) {
            null // provider failure/permission loss: no fabricated grant
        }
    }

    private fun verifyPersistedPermission(
        context: Context,
        uri: Uri?,
        mode: SafAccessMode,
    ): Boolean? {
        if (uri == null || uri.scheme != "content") return false
        return try {
            context.contentResolver.persistedUriPermissions.any { grant ->
                grant.uri == uri && when (mode) {
                    SafAccessMode.READ -> grant.isReadPermission
                    SafAccessMode.WRITE -> grant.isWritePermission
                }
            }
        } catch (_: RuntimeException) {
            null
        }
    }
}

package org.androidmcp.nativeapp

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.androidmcp.protocol.NativePackageDetailResult
import org.androidmcp.protocol.NativePackageDetailSource
import org.androidmcp.protocol.NativePackageDetails
import org.androidmcp.protocol.NativePackageRequest
import java.security.MessageDigest

/**
 * Internal-only, explicit single visible-package lookup for this app's user.
 *
 * Before EACH request, re-evaluates the platform-filtered visible subset.
 * Unknown/hidden/uninstalled packages are indistinguishable via Android
 * package visibility. Never guesses a second user or uses broad flags.
 */
internal object AndroidTargetPackageReader {
    fun read(context: Context, packageName: String): NativePackageDetailResult {
        val request = NativePackageRequest(packageName, userScope = "current")
        val api = Build.VERSION.SDK_INT
        val currentlyVisible = AndroidVisiblePackagesReader.read(context)
        if (!NativePackageDetails.validPackageName(packageName) ||
            currentlyVisible.lookup(packageName) !=
            org.androidmcp.protocol.VisiblePackageLookup.VISIBLE
        ) {
            return NativePackageDetails.resolve(api, request, currentlyVisible, null)
        }

        val packageInfo = try {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(
                packageName,
                PackageManager.GET_SIGNING_CERTIFICATES or PackageManager.GET_ACTIVITIES,
            )
        } catch (_: PackageManager.NameNotFoundException) {
            return NativePackageDetails.resolve(api, request, currentlyVisible, null)
        } catch (_: RuntimeException) {
            return NativePackageDetails.unavailable()
        }

        val app = packageInfo.applicationInfo ?: return NativePackageDetails.unavailable()
        val digest = try {
            val signingInfo = packageInfo.signingInfo
            val signers = signingInfo?.apkContentsSigners
            // The certificate digest is public app signing metadata; do not
            // reveal full cert bytes, an account token, or private keys.
            if (signers?.size != 1) null else {
                MessageDigest.getInstance("SHA-256")
                    .digest(signers.single().toByteArray())
                    .joinToString("") { "%02x".format(it) }
            }
        } catch (_: RuntimeException) {
            null
        }

        return NativePackageDetails.resolve(
            api,
            request,
            currentlyVisible,
            NativePackageDetailSource(
                packageName = packageInfo.packageName,
                installed = true,
                enabled = app.enabled,
                versionName = packageInfo.versionName,
                versionCode = packageInfo.longVersionCode,
                certificateSha256 = digest,
                hasExportedActivity = packageInfo.activities?.any { it.exported } ?: false,
            ),
        )
    }
}

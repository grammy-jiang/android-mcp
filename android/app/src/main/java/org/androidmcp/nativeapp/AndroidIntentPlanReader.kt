package org.androidmcp.nativeapp

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import org.androidmcp.protocol.NativeIntentPlanResult
import org.androidmcp.protocol.NativeIntentPlans
import org.androidmcp.protocol.NativeIntentPlanner
import org.androidmcp.protocol.NativeIntentRequest
import org.androidmcp.protocol.NativeLaunchEnvironment
import org.androidmcp.protocol.NativePackageVisibility
import org.androidmcp.protocol.NativeResolvedActivity
import org.androidmcp.protocol.VisibleActivityResolver

/**
 * Private read-only explicit-component resolution. This adapter *never*
 * launches an Intent or changes Android tasks, grants or preferences.
 * A real Activity owner must supply a locally approved component allowlist
 * and fresh foreground/user-interaction state. No public Tool invokes this.
 */
internal object AndroidIntentPlanReader {
    fun plan(
        context: Context,
        request: NativeIntentRequest,
        localAllowlistedComponents: Set<String>,
        isCallerActivityForeground: Boolean,
        explicitUserGestureObserved: Boolean,
    ): NativeIntentPlanResult {
        val environment = NativeLaunchEnvironment(
            apiLevel = Build.VERSION.SDK_INT,
            callerForeground = isCallerActivityForeground,
            userGestureObserved = explicitUserGestureObserved,
        )
        // Always reject malformed/implicit/cross-user/background requests
        // before querying a PackageManager that might itself be slow.
        if (NativeIntentPlans.preflight(
                request, environment, localAllowlistedComponents,
            ) != null
        ) {
            return NativeIntentPlans.resolve(
                request, environment,
                NativePackageVisibility.unavailable(),
                localAllowlistedComponents, null,
            )
        }
        val visible = AndroidVisiblePackagesReader.read(context)
        return NativeIntentPlanner.plan(
            request, environment, visible, localAllowlistedComponents,
            VisibleActivityResolver { candidate ->
                val component = ComponentName(
                    candidate.packageName, candidate.activityName,
                )
                val resolved = try {
                    @Suppress("DEPRECATION")
                    context.packageManager.getActivityInfo(component, 0)
                } catch (_: PackageManager.NameNotFoundException) {
                    null
                }
                resolved?.let {
                    NativeResolvedActivity(
                        packageName = it.packageName,
                        activityName = it.name,
                        exported = it.exported,
                        enabled = it.enabled,
                    )
                }
            },
        )
    }
}

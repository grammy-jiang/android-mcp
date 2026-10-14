package org.androidmcp.nativeapp

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * E01.a: executes in the installed Android app under AndroidJUnitRunner.
 * These are real Android API observations, not JVM mocks or MCP E2E receipts.
 * The separate E01.d client must prove the live MCP transport.
 */
@RunWith(AndroidJUnit4::class)
class NativeFrameworkBaselineTest {
    private val targetContext
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun installedApplicationIsObservableThroughRealPackageManager() {
        val context = targetContext
        val installed = context.packageManager.getPackageInfo(context.packageName, 0)
        assertEquals("org.androidmcp.nativeapp", installed.packageName)
        assertEquals(context.applicationInfo.uid, installed.applicationInfo!!.uid)
        assertTrue(installed.longVersionCode >= 1L)
        assertTrue(Build.VERSION.SDK_INT in listOf(30, 33, 34, 36))
        assertTrue(SystemClock.elapsedRealtime() > 0L)
    }

    @Test
    fun installedManifestHasExplicitLocalPreviewAndNoPrivilegedWildcard() {
        val context = targetContext
        @Suppress("DEPRECATION")
        val installed = context.packageManager.getPackageInfo(
            context.packageName,
            PackageManager.GET_PERMISSIONS or PackageManager.GET_ACTIVITIES
        )
        val permissions = (installed.requestedPermissions ?: emptyArray()).toSet()
        assertTrue(Manifest.permission.INTERNET in permissions)
        assertFalse("android.permission.QUERY_ALL_PACKAGES" in permissions)
        assertFalse("android.permission.MANAGE_EXTERNAL_STORAGE" in permissions)
        assertFalse("android.permission.WRITE_SECURE_SETTINGS" in permissions)
        val main = installed.activities?.singleOrNull {
            it.name == NativeMcpActivity::class.java.name
        }
        assertNotNull("Installed APK must expose its legitimate local launcher", main)
        assertTrue(main!!.exported)
        assertEquals(
            PackageManager.PERMISSION_GRANTED,
            context.checkSelfPermission(Manifest.permission.INTERNET)
        )
    }

    @Test
    fun realSystemServicesAreAccessibleWithoutPrivilegedConsent() {
        val context = targetContext
        val notificationManager = context.getSystemService(android.app.NotificationManager::class.java)
        assertNotNull(notificationManager)
        val activityManager = context.getSystemService(android.app.ActivityManager::class.java)
        assertNotNull(activityManager)
        assertTrue(context.filesDir.absolutePath.startsWith("/data/user/"))
    }
}

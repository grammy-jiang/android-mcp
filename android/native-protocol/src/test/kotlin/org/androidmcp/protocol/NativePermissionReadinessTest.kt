package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class NativePermissionReadinessTest {
    private fun snapshot(api: Int, grants: Map<String, Boolean?> = emptyMap()) =
        NativePermissionReadiness(api, AndroidPermissionProbe { grants[it] }).snapshot()

    @Test
    fun tN0D01ApiPermissionTuplesHaveStrictStates() {
        val modern = snapshot(36, mapOf(
            "android.permission.INTERNET" to true,
            "android.permission.FOREGROUND_SERVICE" to true,
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE" to true,
            "android.permission.POST_NOTIFICATIONS" to false,
        ))
        assertEquals(1, modern.schemaVersion)
        assertEquals(PermissionReadiness.GRANTED, modern.readiness(NativePermissionCapability.LOOPBACK))
        assertEquals(PermissionReadiness.DENIED, modern.readiness(NativePermissionCapability.NOTIFICATIONS))
        assertEquals(PermissionReadiness.GRANTED, modern.readiness(NativePermissionCapability.FOREGROUND_SERVICE))
        assertEquals(PermissionReadiness.UNKNOWN, snapshot(36).readiness(NativePermissionCapability.NOTIFICATIONS))
        assertEquals(PermissionReadiness.NOT_APPLICABLE, snapshot(30).readiness(NativePermissionCapability.NOTIFICATIONS))
        assertEquals(PermissionReadiness.UNSUPPORTED, snapshot(30).readiness(NativePermissionCapability.FOREGROUND_SERVICE))
    }

    @Test
    fun tN0D02UnmanifestedSensitivePermissionsCannotBeGrantedByProbe() {
        val grantEverything = NativePermissionReadiness(
            36, AndroidPermissionProbe { true },
        ).snapshot()
        for (capability in listOf(
            NativePermissionCapability.ACCESSIBILITY,
            NativePermissionCapability.MEDIA_PROJECTION,
            NativePermissionCapability.PACKAGE_VISIBILITY,
            NativePermissionCapability.DEVICE_ADMIN,
            NativePermissionCapability.PRIVILEGED,
        )) {
            assertFalse(grantEverything.readiness(capability) == PermissionReadiness.GRANTED)
        }
        assertFalse(grantEverything.states.keys.any { it.key.contains("serial") })
    }

    @Test
    fun tN0D03OlderApisDoNotRequestRuntimeNotificationPermission() {
        val queried = mutableListOf<String>()
        val grant = AndroidPermissionProbe {
            queried.add(it)
            true
        }
        val old = NativePermissionReadiness(30, grant).snapshot()
        assertEquals(PermissionReadiness.NOT_APPLICABLE, old.readiness(NativePermissionCapability.NOTIFICATIONS))
        assertFalse(queried.contains("android.permission.POST_NOTIFICATIONS"))
        assertFalse(old.foregroundMayStart())
        val api33 = NativePermissionReadiness(33, grant).snapshot()
        assertEquals(PermissionReadiness.GRANTED, api33.readiness(NativePermissionCapability.NOTIFICATIONS))
        assertFalse(api33.foregroundMayStart())
        val api34Denied = snapshot(34, mapOf(
            "android.permission.INTERNET" to true,
            "android.permission.FOREGROUND_SERVICE" to true,
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE" to true,
            "android.permission.POST_NOTIFICATIONS" to false,
        ))
        assertFalse(api34Denied.foregroundMayStart())
    }

    @Test
    fun tN0D04RevocationIsObservedFreshAndDeniedForNewStarts() {
        val notificationGranted = AtomicBoolean(true)
        val checked = AtomicInteger()
        val model = NativePermissionReadiness(34, AndroidPermissionProbe {
            checked.incrementAndGet()
            if (it == "android.permission.POST_NOTIFICATIONS") notificationGranted.get() else true
        })
        val before = model.snapshot()
        assertTrue(before.foregroundMayStart())
        notificationGranted.set(false)
        val after = model.snapshot()
        assertFalse(after.foregroundMayStart())
        assertEquals(PermissionReadiness.DENIED, after.readiness(NativePermissionCapability.NOTIFICATIONS))
        assertTrue(checked.get() >= 6)
        assertFalse(after.readiness(NativePermissionCapability.MEDIA_PROJECTION) == PermissionReadiness.GRANTED)
    }

    @Test
    fun tN0D05ExceptionOrUnavailableServiceFailsUnknownWithoutRetryLoop() {
        val calls = AtomicInteger()
        val model = NativePermissionReadiness(36, AndroidPermissionProbe {
            calls.incrementAndGet()
            throw SecurityException("synthetic OEM failure secret=do-not-echo")
        })
        val result = model.snapshot()
        assertEquals(PermissionReadiness.UNKNOWN, result.readiness(NativePermissionCapability.NOTIFICATIONS))
        assertFalse(result.foregroundMayStart())
        assertTrue(calls.get() in 1..6)
        assertThrows(IllegalArgumentException::class.java) {
            NativePermissionReadiness(-1, AndroidPermissionProbe { true })
        }
    }

    @Test
    fun tN0D06CoarseVersionedSnapshotHasNoSensitiveData() {
        val data = NativePermissionReadiness(36, AndroidPermissionProbe { false }).snapshot()
        val output = data.encode()
        val root = Json.parseToJsonElement(output).jsonObject
        assertEquals(setOf("schema_version", "api_level", "permissions"), root.keys)
        assertEquals("1", root.getValue("schema_version").jsonPrimitive.content)
        assertEquals("36", root.getValue("api_level").jsonPrimitive.content)
        assertTrue(output.toByteArray().size < 4096)
        for (secret in listOf("serial", "advertising", "device_id", "packages", "token", "private")) {
            assertFalse(output.contains(secret))
        }
        assertFalse(data.foregroundMayStart())
    }

    @Test
    fun supplementaryForegroundGrantRequiresBothDeclaredFgsPermissions() {
        val permissions = mapOf(
            NativePermissionReadiness.INTERNET to true,
            NativePermissionReadiness.POST_NOTIFICATIONS to true,
            NativePermissionReadiness.FOREGROUND_SERVICE to true,
            NativePermissionReadiness.FOREGROUND_SPECIAL_USE to false,
        )
        val denied = snapshot(36, permissions)
        assertEquals(PermissionReadiness.DENIED, denied.readiness(NativePermissionCapability.FOREGROUND_SERVICE))
        assertFalse(denied.foregroundMayStart())
        val missing = snapshot(36, permissions - NativePermissionReadiness.FOREGROUND_SPECIAL_USE)
        assertEquals(PermissionReadiness.UNKNOWN, missing.readiness(NativePermissionCapability.FOREGROUND_SERVICE))
        assertFalse(missing.foregroundMayStart())
        val bothGranted = snapshot(36, permissions + (
            NativePermissionReadiness.FOREGROUND_SPECIAL_USE to true
        ))
        assertTrue(bothGranted.foregroundMayStart())
    }

    @Test
    fun supplementarySnapshotDoesNotPersistOriginalPermissionProbeOrExceptions() {
        val values = mutableListOf<String>()
        val model = NativePermissionReadiness(36, AndroidPermissionProbe { name ->
            values.add(name)
            throw IllegalStateException("synthetic secret password=my-private-password")
        })
        val first = model.snapshot()
        val second = model.snapshot()
        assertFalse(first.foregroundMayStart())
        assertFalse(second.foregroundMayStart())
        assertEquals(PermissionReadiness.UNKNOWN, first.readiness(NativePermissionCapability.LOOPBACK))
        assertEquals(PermissionReadiness.UNKNOWN, second.readiness(NativePermissionCapability.FOREGROUND_SERVICE))
        assertEquals(8, values.size)
        assertFalse(first.encode().contains("password"))
        assertFalse(second.encode().contains("secret"))
    }
}

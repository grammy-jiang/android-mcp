package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeBuildSnapshotTest {
    private fun expected(api: Int = 36) = NativeBuildSnapshots.normalize(
        apiLevel = api,
        osRelease = "16",
        manufacturer = "Google",
        model = "SDK phone",
        supportedAbis = listOf("arm64-v8a", "armeabi-v7a"),
        appVersion = "0.1.0",
    )

    @Test
    fun tN1A01RepresentativeBuildApiAbisNormalizeToVersionedSnapshot() {
        val snapshot = expected()
        assertEquals(1, snapshot.schemaVersion)
        assertEquals("android", snapshot.runtime)
        assertEquals(NativeBuildAvailability.AVAILABLE, snapshot.availability)
        assertEquals(36, snapshot.apiLevel)
        assertEquals(listOf("arm64-v8a", "armeabi-v7a"), snapshot.supportedAbis)
        val wire = Json.parseToJsonElement(snapshot.encode()).jsonObject
        assertEquals(1, wire.getValue("schema_version").jsonPrimitive.content.toInt())
        assertEquals("available", wire.getValue("availability").jsonPrimitive.content)
        assertEquals("android", wire.getValue("runtime").jsonPrimitive.content)
        assertEquals(2, wire.getValue("supported_abis").jsonArray.size)
    }

    @Test
    fun tN1A02PersistentIdentifiersNeverEnterSnapshotOutput() {
        val crafted = NativeBuildSnapshots.normalize(
            36, "16", "Google", "serial=123456token", listOf("arm64-v8a"), "0.1.0"
        )
        val output = crafted.encode().lowercase()
        for (name in listOf(
            "serial", "device_id", "android_id", "advertising_id",
            "imei", "imsi", "fingerprint", "mac_address", "private_key", "123456token",
        )) {
            assertFalse(output.contains(name))
        }
        assertNull(crafted.model)
        assertEquals(NativeBuildAvailability.PARTIAL, crafted.availability)
    }

    @Test
    fun tN1A03MissingOemFieldsAndOddAbisRemainExplicitPartial() {
        val incomplete = NativeBuildSnapshots.normalize(
            34, null, "", " ", listOf("arm64-v8a", "../../dev/", "arm64-v8a"), null
        )
        assertEquals(NativeBuildAvailability.PARTIAL, incomplete.availability)
        assertNull(incomplete.osRelease)
        assertNull(incomplete.manufacturer)
        assertNull(incomplete.model)
        assertNull(incomplete.appVersion)
        assertEquals(listOf("arm64-v8a"), incomplete.supportedAbis)
        assertFalse(incomplete.encode().contains("../"))
        val unknown = NativeBuildSnapshots.normalize(null, null, null, null, null, null)
        assertEquals(NativeBuildAvailability.UNSUPPORTED, unknown.availability)
        assertEquals(emptyList<String>(), unknown.supportedAbis)
    }

    @Test
    fun tN1A04Api30_33_34_36SupportedAndEarlierDenied() {
        for (api in listOf(30, 33, 34, 36)) {
            val status = expected(api)
            assertEquals(NativeBuildAvailability.AVAILABLE, status.availability)
            assertEquals(api, status.apiLevel)
            assertEquals("arm64-v8a", status.supportedAbis.first())
        }
        assertEquals(
            NativeBuildAvailability.UNSUPPORTED,
            expected(29).availability,
        )
        assertEquals(
            NativeBuildAvailability.UNSUPPORTED,
            expected(-1).availability,
        )
    }

    @Test
    fun tN1A05OversizeInvalidUnicodeAndMalformedAbisAreBounded() {
        val malformed = NativeBuildSnapshots.normalize(
            apiLevel = 36,
            osRelease = "16\nTOKEN=private",
            manufacturer = "X".repeat(999_999),
            model = "\uD800", // unsupported lone surrogate
            supportedAbis = listOf("a".repeat(99999), "arm64-v8a", "bad;abi"),
            appVersion = "0.1.0",
        )
        val encoded = malformed.encode()
        assertTrue(encoded.toByteArray(Charsets.UTF_8).size <= 4096)
        assertFalse(encoded.contains("private"))
        assertFalse(encoded.contains("X".repeat(100)))
        assertFalse(encoded.contains("\\ud800", ignoreCase = true))
        assertEquals(listOf("arm64-v8a"), malformed.supportedAbis)
        assertEquals(NativeBuildAvailability.PARTIAL, malformed.availability)
        assertNull(malformed.osRelease)
        assertNull(malformed.manufacturer)
        assertNull(malformed.model)
    }

    @Test
    fun tN1A06UnpairedSensitiveProfileRemainsDisabled() {
        val status = expected()
        assertEquals(NativeBuildAvailability.AVAILABLE, status.availability)
        val guard = NativeLocalCallerGuard()
        val caller = LocalHttpRequest(origin = "http://127.0.0.1:38765")
        assertFalse(guard.authorizeSensitive(caller, "native_build_snapshot").allowed)
        assertFalse(guard.authorizeSensitive(
            caller, "native_build_snapshot",
            SyntheticCallerApproval(guard.epoch, "synthetic", true),
        ).allowed)
        assertTrue(NativeLocalStatus.encode().contains("android.native.loopback_status"))
        assertFalse(NativeLocalStatus.encode().contains("manufacturer"))
    }
}

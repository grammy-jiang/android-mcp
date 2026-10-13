package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeHostFallbackTest {
    private val now = 10_000L
    private fun host() = FakeHostProbe(
        hostKey = "host-public-key-fingerprint",
        bootEpoch = "host-boot-epoch", serial = "R3C1ADB",
        online = true, transportVerified = true, signedIdentityVerified = true,
        observedAtElapsedMs = 9500L,
    )
    private fun native() = FakeNativeProbe(
        installationId = "private-native-install-id",
        bootEpoch = "native-boot-epoch",
        userStarted = true, loopbackListening = true, appForeground = true,
        observedAtElapsedMs = 9600L,
    )
    private fun binding() = FakeHostNativeBinding(
        hostKeyFromProbe(), host().bootEpoch, host().serial,
        native().installationId, native().bootEpoch,
        expiryElapsedMs = 20_000,
    )
    private fun hostKeyFromProbe() = host().hostKey

    @Test
    fun tN5D01HostAliveNativeDeadReturnsDistinctReadOnlyHostFallback() {
        val result = NativeHostFallback.evaluate(
            host(), native().copy(loopbackListening = false), binding(), now,
        )
        assertEquals(FallbackDecision.HOST_READ_ONLY, result.decision)
        assertEquals(FallbackAvailability.AVAILABLE, result.host)
        assertEquals(FallbackAvailability.OFFLINE, result.native)
        assertEquals(listOf(FallbackProvider.HOST_ADB), result.providers)
        assertEquals(FallbackCall.SUGGEST_READ_ONLY,
            NativeHostFallback.planCall(FallbackAction.HOST_ADB_OBSERVE, result))
        assertEquals(FallbackCall.UNAVAILABLE,
            NativeHostFallback.planCall(FallbackAction.NATIVE_STATUS, result))
        assertFalse(result.encode().contains("R3C1ADB"))
    }

    @Test
    fun tN5D02HostOfflineNativeUserStartedOnlyNativeStatusIsAvailable() {
        val result = NativeHostFallback.evaluate(
            host().copy(online = false), native(), binding(), now,
        )
        assertEquals(FallbackDecision.NATIVE_READ_ONLY, result.decision)
        assertEquals(FallbackAvailability.OFFLINE, result.host)
        assertEquals(FallbackAvailability.AVAILABLE, result.native)
        assertEquals(listOf(FallbackProvider.NATIVE_LOOPBACK), result.providers)
        assertEquals(FallbackCall.SUGGEST_READ_ONLY,
            NativeHostFallback.planCall(FallbackAction.NATIVE_STATUS, result))
        assertEquals(FallbackCall.UNAVAILABLE,
            NativeHostFallback.planCall(FallbackAction.HOST_ADB_OBSERVE, result))
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
    }

    @Test
    fun tN5D03BothAvailableOrBothUnavailableDoNotAutoselectFirstProvider() {
        val both = NativeHostFallback.evaluate(host(), native(), binding(), now)
        assertEquals(FallbackDecision.BOTH_AVAILABLE, both.decision)
        assertEquals(
            listOf(FallbackProvider.HOST_ADB, FallbackProvider.NATIVE_LOOPBACK),
            both.providers,
        )
        assertEquals("false",
            Json.parseToJsonElement(both.encode()).jsonObject
                .getValue("automatic_failover").jsonPrimitive.content)
        val neither = NativeHostFallback.evaluate(
            host().copy(online = false), native().copy(loopbackListening = false),
            binding(), now,
        )
        assertEquals(FallbackDecision.UNAVAILABLE, neither.decision)
        assertTrue(neither.providers.isEmpty())
        val unknown = NativeHostFallback.evaluate(
            host().copy(online = null), null, binding(), now,
        )
        assertEquals(FallbackDecision.UNKNOWN, unknown.decision)
        assertEquals(FallbackAvailability.UNKNOWN, unknown.host)
    }

    @Test
    fun tN5D04ReinstallBootEpochSerialReuseAndUsbDisconnectInvalidateBinding() {
        val scenarios = listOf(
            host() to native().copy(installationId = "new-install-id"),
            host().copy(bootEpoch = "rebooted-host") to native(),
            host() to native().copy(bootEpoch = "rebooted-native"),
            host().copy(serial = "R3C1ADB-reused") to native(),
            host().copy(signedIdentityVerified = false) to native(),
            host().copy(transportVerified = false) to native(),
        )
        for ((left, right) in scenarios) {
            val denied = NativeHostFallback.evaluate(left, right, binding(), now)
            assertEquals(FallbackDecision.STALE_BINDING, denied.decision)
            assertTrue(denied.providers.isEmpty())
            assertEquals(FallbackCall.UNAVAILABLE,
                NativeHostFallback.planCall(FallbackAction.HOST_ADB_OBSERVE, denied))
        }
        val staleTime = NativeHostFallback.evaluate(host(), native(), binding(), 40_000)
        assertEquals(FallbackDecision.STALE_BINDING, staleTime.decision)
    }

    @Test
    fun tN5D05LostWriteLeaseNeverEnablesHostOrNativeMutations() {
        val binding = binding().copy(writeLeaseActive = false)
        val result = NativeHostFallback.evaluate(host(), native(), binding, now)
        for (operation in listOf(
            FallbackAction.INSTALL_APK, FallbackAction.ROOT,
            FallbackAction.UI_WRITE, FallbackAction.ACCESSIBILITY,
            FallbackAction.REBOOT,
        )) {
            assertEquals(FallbackCall.DENIED, NativeHostFallback.planCall(operation, result))
        }
        val fakeLease = NativeHostFallback.evaluate(
            host(), native(), binding.copy(writeLeaseActive = true), now)
        assertEquals(FallbackCall.DENIED,
            NativeHostFallback.planCall(FallbackAction.INSTALL_APK, fakeLease))
        assertEquals(FallbackCall.DENIED,
            NativeHostFallback.planCall(FallbackAction.UI_WRITE, fakeLease))
    }

    @Test
    fun tN5D06FakeInteractionsAreTypedNoHostUsbAdbOrPhysicalMutation() {
        val response = NativeHostFallback.evaluate(host(), native(), binding(), now)
        assertEquals(FallbackCall.UNSUPPORTED,
            NativeHostFallback.planCall(FallbackAction.UNKNOWN, response))
        assertEquals(FallbackCall.SUGGEST_READ_ONLY,
            NativeHostFallback.planCall(FallbackAction.NATIVE_STATUS, response))
        val json = Json.parseToJsonElement(response.encode()).jsonObject
        assertEquals("1", json.getValue("schema_version").jsonPrimitive.content)
        assertEquals("both_available", json.getValue("decision").jsonPrimitive.content)
        assertEquals(2, json.getValue("providers").jsonArray.size)
        for (secret in listOf(
            "host-public-key-fingerprint", "private-native-install-id",
            "R3C1ADB", "native-boot-epoch", "host-boot-epoch",
            "private_key", "token", "usb_path", "serial",
        )) assertFalse(response.encode().contains(secret))
        assertTrue(response.encode().toByteArray().size < 2048)
    }

    @Test
    fun serialWithoutBindingOrVerifiedSignerIsNotTrustedDeviceIdentity() {
        val known = host()
        assertEquals(FallbackDecision.DENIED,
            NativeHostFallback.evaluate(known, native(), null, now).decision)
        assertEquals(FallbackDecision.STALE_BINDING,
            NativeHostFallback.evaluate(
                known.copy(hostKey = "forged-host-key"), native(), binding(), now,
            ).decision)
        assertEquals(FallbackDecision.STALE_BINDING,
            NativeHostFallback.evaluate(
                known.copy(signedIdentityVerified = false), native(), binding(), now,
            ).decision)
        assertEquals(FallbackDecision.DENIED,
            NativeHostFallback.evaluate(
                known, native(), binding().copy(expectedHostKey = "../../../private"), now,
            ).decision)
    }

    @Test
    fun staleObservationAndDisconnectedForegroundCannotClaimNativeReady() {
        val stale = NativeHostFallback.evaluate(
            host().copy(observedAtElapsedMs = 10L), native(), binding(), now,
        )
        assertEquals(FallbackAvailability.STALE, stale.host)
        assertEquals(FallbackDecision.NATIVE_READ_ONLY, stale.decision)
        assertEquals(FallbackCall.UNAVAILABLE,
            NativeHostFallback.planCall(FallbackAction.HOST_ADB_OBSERVE, stale))
        val bothStale = NativeHostFallback.evaluate(
            host().copy(observedAtElapsedMs = 10L),
            native().copy(observedAtElapsedMs = 20L), binding(), now,
        )
        assertEquals(FallbackDecision.UNAVAILABLE, bothStale.decision)
        val stopped = NativeHostFallback.evaluate(
            host(), native().copy(userStarted = false), binding(), now,
        )
        assertEquals(FallbackDecision.HOST_READ_ONLY, stopped.decision)
        assertEquals(FallbackCall.UNAVAILABLE,
            NativeHostFallback.planCall(FallbackAction.NATIVE_STATUS, stopped))
    }
}

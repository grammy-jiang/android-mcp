package org.androidmcp.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class NativeOwnPerformanceTest {
    private fun input(session: NativeOwnPerformanceSession, api: Int = 36) =
        OwnPerformanceInput(
            api, session.epoch, 10_000L,
            ownProcessCpuMs = 2_000L,
            ownJavaHeapUsedBytes = 4_194_304L,
            ownNativeHeapUsedBytes = 1_048_576L,
            eventLatencyMs = 25L,
            processAlive = true,
            appForeground = true,
        )

    @Test
    fun tN5B01OwnProcessCountersHaveStableUnitsAndEpochIdentity() {
        val session = NativeOwnPerformanceSession()
        val result = session.sample(input(session))
        assertEquals(OwnPerformanceStatus.AVAILABLE, result.status)
        assertEquals(36, result.apiLevel)
        assertEquals(10_000L, result.sampledElapsedMs)
        assertEquals(2_000L, result.ownProcessCpuMs)
        assertEquals(4_194_304L, result.ownJavaHeapUsedBytes)
        assertEquals(1_048_576L, result.ownNativeHeapUsedBytes)
        assertEquals(25L, result.eventLatencyMs)
        val json = Json.parseToJsonElement(result.encode()).jsonObject
        assertEquals("1", json.getValue("schema_version").jsonPrimitive.content)
        assertEquals("available", json.getValue("status").jsonPrimitive.content)
        assertEquals("android", json.getValue("runtime").jsonPrimitive.content)
    }

    @Test
    fun tN5B02GlobalProfilingRootPerfettoAndForeignPidRequestsDenied() {
        val session = NativeOwnPerformanceSession()
        val denied = session.sample(input(session).copy(requestGlobalProfile = true))
        assertEquals(OwnPerformanceStatus.DENIED, denied.status)
        assertNull(denied.ownProcessCpuMs)
        assertFalse(session.globalProfilerAllowed())
        assertFalse(session.liveBackgroundSamplingAllowed())
        assertFalse(denied.encode().contains("pid"))
        assertFalse(denied.encode().contains("perfetto"))
    }

    @Test
    fun tN5B03Api30_33_34_36PartialAndInvalidOemSampleValuesFailClosed() {
        for (api in listOf(30, 33, 34, 36)) {
            val session = NativeOwnPerformanceSession()
            assertEquals(OwnPerformanceStatus.AVAILABLE,
                session.sample(input(session, api)).status)
        }
        val prior = NativeOwnPerformanceSession()
        assertEquals(OwnPerformanceStatus.UNSUPPORTED,
            prior.sample(input(prior, 29)).status)
        val broken = NativeOwnPerformanceSession()
        val result = broken.sample(input(broken).copy(
            ownProcessCpuMs = -1,
            ownJavaHeapUsedBytes = Long.MAX_VALUE,
            eventLatencyMs = -10,
        ))
        assertEquals(OwnPerformanceStatus.PARTIAL, result.status)
        assertNull(result.ownProcessCpuMs)
        assertNull(result.ownJavaHeapUsedBytes)
        assertNull(result.eventLatencyMs)
    }

    @Test
    fun tN5B04FgsStopSleepOrRestartCannotReportStaleMetrics() {
        for (reason in OwnPerformanceStop.entries) {
            val session = NativeOwnPerformanceSession()
            assertEquals(OwnPerformanceStatus.AVAILABLE,
                session.sample(input(session)).status)
            session.stop(reason)
            val stopped = session.sample(input(session).copy(sampledElapsedMs = 20_000))
            assertEquals(OwnPerformanceStatus.STOPPED, stopped.status)
            assertNull(stopped.ownJavaHeapUsedBytes)
            assertEquals(0, session.sampleCount())
        }
        val first = NativeOwnPerformanceSession()
        val newInstance = NativeOwnPerformanceSession()
        assertNotEquals(first.epoch, newInstance.epoch)
        assertEquals(OwnPerformanceStatus.DENIED,
            newInstance.sample(input(first)).status)
    }

    @Test
    fun tN5B05HighRateAndLongSampleRequestsAreThrottledAndCapped() {
        val session = NativeOwnPerformanceSession()
        for (i in 0 until 16) {
            val sample = session.sample(input(session).copy(
                sampledElapsedMs = 10_000L + 1_000L * i,
                ownProcessCpuMs = 2_000L + 10L * i,
            ))
            assertEquals(OwnPerformanceStatus.AVAILABLE, sample.status)
        }
        assertEquals(16, session.sampleCount())
        assertEquals(OwnPerformanceStatus.THROTTLED,
            session.sample(input(session).copy(sampledElapsedMs = 26_000)).status)
        assertEquals(OwnPerformanceStatus.THROTTLED,
            session.sample(input(session).copy(
                sampledElapsedMs = 30_000, requestHighRateStream = true,
            )).status)
        assertFalse(session.liveBackgroundSamplingAllowed())
    }

    @Test
    fun tN5B06PublicStatusCannotExposeOtherProcessIdsOrPrivateBacktraces() {
        val session = NativeOwnPerformanceSession()
        val encoded = session.sample(input(session)).encode().lowercase()
        for (forbidden in listOf(
            "pid", "process_name", "stacktrace", "token", "account",
            "ssid", "bssid", "device_id", "location", "raw_trace",
            "other_package", "private_path", "root",
        )) assertFalse(encoded.contains(forbidden))
        assertTrue(encoded.toByteArray().size < 4096)
        assertEquals(listOf("device_status"),
            NativeToolProfiles().liveTools(true).map { it.name })
    }

    @Test
    fun concurrentSameInstantSamplesCannotBypassIntervalOrBufferCaps() {
        val session = NativeOwnPerformanceSession()
        val pool = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val go = CountDownLatch(1)
        try {
            val futures = (0 until 8).map {
                pool.submit<OwnPerformanceResult> {
                    ready.countDown()
                    go.await(5, TimeUnit.SECONDS)
                    session.sample(input(session))
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            go.countDown()
            val results = futures.map { it.get(5, TimeUnit.SECONDS) }
            assertEquals(1, results.count { it.status == OwnPerformanceStatus.AVAILABLE })
            assertEquals(7, results.count { it.status == OwnPerformanceStatus.THROTTLED })
            assertEquals(1, session.sampleCount())
        } finally {
            go.countDown()
            pool.shutdownNow()
        }
    }

    @Test
    fun cpuCounterGoingBackwardsCannotClaimContinuousOwnProcess() {
        val session = NativeOwnPerformanceSession()
        assertEquals(OwnPerformanceStatus.AVAILABLE, session.sample(input(session)).status)
        val stale = session.sample(input(session).copy(
            sampledElapsedMs = 12_000L,
            ownProcessCpuMs = 1_500L,
        ))
        assertEquals(OwnPerformanceStatus.UNAVAILABLE, stale.status)
        assertNull(stale.ownProcessCpuMs)
        assertEquals(0, session.sampleCount())
        assertFalse(session.globalProfilerAllowed())
    }
}

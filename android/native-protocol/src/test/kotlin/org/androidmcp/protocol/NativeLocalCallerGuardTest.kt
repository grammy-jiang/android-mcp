package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Each N0.b case is test-first; a Kotlin fake never proves Android caller identity. */
class NativeLocalCallerGuardTest {
    private val approved = LocalHttpRequest(origin = "http://127.0.0.1:38765")

    @Test
    fun tN0B01SyntheticApprovalRecognizedButNoSensitiveToolEnabled() {
        val guard = NativeLocalCallerGuard()
        val proof = SyntheticCallerApproval(guard.epoch, "challenge-1", true)
        assertEquals("RECOGNIZED_INERT", guard.recognizeSynthetic(approved, proof).code)
        assertFalse(guard.authorizeSensitive(approved, "native_screen_capture", proof).allowed)
    }

    @Test
    fun tN0B02LoopbackUntrustedAppNeverAuthorizesSensitiveTools() {
        val guard = NativeLocalCallerGuard()
        val untrusted = LocalHttpRequest(remoteHost = "127.0.0.1", origin = null)
        assertTrue(guard.evaluate(untrusted).allowed) // legacy PUBLIC status only
        assertFalse(guard.authorizeSensitive(untrusted, "native_accessibility").allowed)
        assertFalse(guard.authorizeSensitive(untrusted, "native_package_inventory").allowed)
        assertFalse(guard.authorizeSensitive(untrusted, "native_package_install").allowed)
    }

    @Test
    fun tN0B03InvalidHostOriginRouteAndPreflightDeniedBeforeHandlers() {
        val guard = NativeLocalCallerGuard()
        val hostile = listOf(
            approved.copy(host = "127.0.0.1.evil.example:38765"),
            approved.copy(host = null),
            approved.copy(origin = "https://evil.example"),
            approved.copy(origin = "null"),
            approved.copy(path = "/admin"),
            approved.copy(method = "OPTIONS"),
            approved.copy(remoteHost = "192.0.2.44"),
            approved.copy(host = "127.0.0.1\r\nX-Injected: 1"),
        )
        for (request in hostile) {
            assertFalse(guard.evaluate(request).allowed, "must deny hostile request")
        }
        // ADB forward can change the external port while preserving
        // the loopback hostname; it does not confer authorization.
        assertTrue(guard.evaluate(approved.copy(host = "127.0.0.1:45678")).allowed)
        assertTrue(guard.evaluate(approved.copy(origin = null)).allowed)
        assertFalse(guard.authorizeSensitive(approved.copy(origin = null), "screen").allowed)
    }

    @Test
    fun tN0B04ReplayOversizeMalformedAndFloodHaveBoundedDenials() {
        val guard = NativeLocalCallerGuard(maxInFlight = 2)
        val proof = SyntheticCallerApproval(guard.epoch, "repeat-id", true)
        assertEquals("RECOGNIZED_INERT", guard.recognizeSynthetic(approved, proof).code)
        assertEquals("NATIVE_REPLAY", guard.recognizeSynthetic(approved, proof).code)
        val bad = listOf(
            approved.copy(contentLength = "131073"),
            approved.copy(contentLength = "-1"),
            approved.copy(contentLength = "not-a-number"),
            approved.copy(contentLength = null),
            approved.copy(transferEncoding = "chunked"),
            approved.copy(headerCount = 999),
            approved.copy(headerBytes = 8193),
            approved.copy(duplicateSecurityHeaders = true),
        )
        bad.forEach { assertFalse(guard.evaluate(it).allowed) }
        val first = guard.begin(approved)
        val second = guard.begin(approved)
        assertTrue(first.verdict.allowed)
        assertTrue(second.verdict.allowed)
        val busy = guard.begin(approved)
        assertEquals(429, busy.verdict.httpStatus)
        busy.close()
        first.close()
        first.close()
        second.close()
        guard.begin(approved).use { assertTrue(it.verdict.allowed) }
    }

    @Test
    fun tN0B05RestartOrSecondInstanceCannotReuseProofOrLoopbackIp() {
        val old = NativeLocalCallerGuard()
        val next = NativeLocalCallerGuard()
        assertNotEquals(old.epoch, next.epoch)
        val stale = SyntheticCallerApproval(old.epoch, "nonce-2", true)
        assertEquals("NATIVE_STALE", next.recognizeSynthetic(approved, stale).code)
        assertFalse(next.authorizeSensitive(approved, "ui_action", stale).allowed)
        assertFalse(next.authorizeSensitive(approved.copy(origin = null), "ui_action").allowed)
    }

    @Test
    fun tN0B06PublicStatusCompatibleAndNoFakeSecretPromoted() {
        val guard = NativeLocalCallerGuard()
        assertTrue(guard.evaluate(LocalHttpRequest(origin = null)).allowed)
        assertTrue(guard.evaluate(approved.copy(method = "GET", contentLength = null)).allowed)
        assertTrue(guard.evaluate(approved.copy(method = "DELETE", contentLength = null)).allowed)
        assertEquals("NATIVE_STATUS_ONLY", guard.evaluate(approved).code)
        assertEquals(
            "NATIVE_SYNTHETIC_ORIGIN_REQUIRED",
            guard.recognizeSynthetic(
                approved.copy(origin = null),
                SyntheticCallerApproval(guard.epoch, "no-origin", true),
            ).code,
        )
        val untrusted = SyntheticCallerApproval(guard.epoch, "id", false)
        assertFalse(guard.recognizeSynthetic(approved, untrusted).allowed)
        assertFalse(guard.authorizeSensitive(approved, "root", untrusted).allowed)
        assertFalse(guard.authorizeSensitive(approved, "screenshot").allowed)
    }

    @Test
    fun inFlightBudgetIsAtomicAcrossSimultaneousRequests() {
        val guard = NativeLocalCallerGuard(maxInFlight = 3)
        val pool = Executors.newFixedThreadPool(12)
        val ready = CountDownLatch(12)
        val start = CountDownLatch(1)
        val running = AtomicInteger(0)
        val peak = AtomicInteger(0)
        try {
            val jobs = (1..12).map {
                pool.submit<Boolean> {
                    ready.countDown()
                    start.await(5, TimeUnit.SECONDS)
                    guard.begin(approved).use { ticket ->
                        if (ticket.verdict.allowed) {
                            val concurrent = running.incrementAndGet()
                            peak.accumulateAndGet(concurrent, ::maxOf)
                            try {
                                Thread.sleep(40)
                            } finally {
                                running.decrementAndGet()
                            }
                        }
                        ticket.verdict.allowed
                    }
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            start.countDown()
            val admitted = jobs.map { it.get(8, TimeUnit.SECONDS) }
            assertTrue(admitted.any { it })
            assertTrue(admitted.any { !it })
            assertTrue(peak.get() in 1..3)
            assertEquals(0, running.get())
            guard.begin(approved).use { assertTrue(it.verdict.allowed) }
        } finally {
            start.countDown()
            pool.shutdownNow()
        }
    }

    @Test
    fun malformedHeadersAndBadPortNeverDegradeIntoStatusOrApproval() {
        val guard = NativeLocalCallerGuard()
        val violations = listOf(
            approved.copy(headerBytes = 8193),
            approved.copy(headerCount = 49),
            approved.copy(duplicateSecurityHeaders = true),
            approved.copy(host = "localhost:65536"),
            approved.copy(host = "localhost:0"),
            approved.copy(host = "localhost:garbage"),
            approved.copy(origin = "http://127.0.0.1:123/path"),
            approved.copy(origin = "https://127.0.0.1:38765"),
        )
        for (bad in violations) {
            assertFalse(guard.begin(bad).use { it.verdict.allowed })
            assertFalse(guard.authorizeSensitive(bad, "any").allowed)
        }
        // The ephemeral port of the ADB forwarded Native status client can
        // legitimately differ from the on-device socket's 38765.
        assertTrue(guard.evaluate(approved.copy(host = "127.0.0.1:58731")).allowed)
    }
}

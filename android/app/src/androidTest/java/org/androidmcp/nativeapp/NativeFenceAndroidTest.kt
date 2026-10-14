package org.androidmcp.nativeapp

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.nio.file.Files
import org.androidmcp.lifecycle.FenceStatus
import org.androidmcp.lifecycle.NativeFenceState
import org.androidmcp.lifecycle.SyntheticFenceRequest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Genuine Android ART regression for bounded N6.c state loading.
 *
 * Test-only synthetic journal; never a Native MCP mutating grant. An Android
 * API30–36 runtime, not just JVM 17, must load the persisted private record.
 */
@RunWith(AndroidJUnit4::class)
class NativeFenceAndroidTest {
    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun actualAndroidReopensPersistedFenceAndRetainsNoMutationAuthority() {
        val root = Files.createTempDirectory(
            context.noBackupFilesDir.toPath(), "v3-fence-regression-"
        )
        val install = "native-install-fixture"
        val boot = "boot-epoch-fixture"
        val host = "host-synthetic-fixture"
        fun state() = NativeFenceState(
            root, install, boot, host, SystemClock::elapsedRealtime
        )
        fun request(fence: Long, digest: String): SyntheticFenceRequest =
            SyntheticFenceRequest(
                nativeInstallation = install,
                bootEpoch = boot,
                hostIdentity = host,
                fence = fence,
                planDigest = digest,
                nonce = "fixture_nonce_$fence",
                expiresAtElapsedMs = SystemClock.elapsedRealtime() + 10_000L,
                fakeHostProofAccepted = true,
            )
        try {
            state().use { first ->
                assertEquals(
                    FenceStatus.SYNTHETIC_RECOGNIZED,
                    first.issue(request(10L, "a".repeat(64))).status,
                )
                assertEquals(10L, first.highWater())
                assertFalse(first.realMutationAllowed())
            }
            state().use { reopened ->
                assertEquals(
                    "Android ART must restore the actual bounded checksum record",
                    10L, reopened.highWater(),
                )
                assertEquals(
                    FenceStatus.STALE,
                    reopened.issue(request(10L, "a".repeat(64))).status,
                )
                assertEquals(
                    FenceStatus.SYNTHETIC_RECOGNIZED,
                    reopened.issue(request(11L, "b".repeat(64))).status,
                )
                assertFalse(reopened.realMutationAllowed())
            }
        } finally {
            assertTrue("No test-only synthetic journal may leak", root.toFile().deleteRecursively())
        }
    }
}

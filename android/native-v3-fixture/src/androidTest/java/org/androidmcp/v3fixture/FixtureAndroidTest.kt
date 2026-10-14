package org.androidmcp.v3fixture

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.provider.DocumentsContract
import android.widget.Button
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Fixture self-test only: not a Native MCP action or SAF grant acceptance.
 */
@RunWith(AndroidJUnit4::class)
class FixtureAndroidTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Test fun syntheticOracleIsStrictlyReadOnly() {
        val oracle = FixtureOracleProvider()
        val info = android.content.pm.ProviderInfo().apply {
            authority = FixtureContract.ORACLE_AUTHORITY
            exported = true
        }
        oracle.attachInfo(context, info)
        val uri = android.net.Uri.parse("content://${FixtureContract.ORACLE_AUTHORITY}/counter")
        val values = android.content.ContentValues().apply { put("counter", 9999) }
        try {
            oracle.insert(uri, values)
            fail("Synthetic oracle must reject insert")
        } catch (_: UnsupportedOperationException) {}
        try {
            oracle.update(uri, values, null, null)
            fail("Synthetic oracle must reject update")
        } catch (_: UnsupportedOperationException) {}
        try {
            oracle.delete(uri, null, null)
            fail("Synthetic oracle must reject delete")
        } catch (_: UnsupportedOperationException) {}
        try {
            oracle.query(
                android.net.Uri.parse("content://${FixtureContract.ORACLE_AUTHORITY}/secret"),
                null, null, null, null
            )
            fail("Synthetic oracle must not reveal other content")
        } catch (_: IllegalArgumentException) {}
    }

    @Test fun parallelFileOpensAreBoundedAndDeterministic() {
        val provider = fixtureProvider()
        val pool = java.util.concurrent.Executors.newFixedThreadPool(4)
        try {
            val futures = (1..12).map {
                pool.submit(java.util.concurrent.Callable {
                    provider.openDocument(FixtureContract.KNOWN_ID, "r", null).use { read ->
                        android.os.ParcelFileDescriptor.AutoCloseInputStream(read).use {
                            it.readBytes()
                        }
                    }
                })
            }
            futures.forEach {
                assertArrayEquals(FixtureContract.knownBytes(),
                    it.get(8, java.util.concurrent.TimeUnit.SECONDS))
            }
        } finally {
            pool.shutdownNow()
            assertTrue(pool.awaitTermination(8, java.util.concurrent.TimeUnit.SECONDS))
        }
    }

    @Test fun knownDocumentContentsAndHashArePinned() {
        val bytes = FixtureContract.knownBytes()
        assertArrayEquals("ANDROID-MCP-V3-FIXTURE-DOCUMENT-v1\n".toByteArray(), bytes)
        assertTrue(bytes.size in 10..256)
    }

    @Test fun buttonMustIncrementPersistentCounter() {
        val prefs = context.getSharedPreferences(FixtureContract.COUNTER_PREFS, 0)
        val before = prefs.getInt(FixtureContract.COUNTER_KEY, 0)
        val intent = Intent(context, FixtureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val activity = instrumentation.startActivitySync(intent) as FixtureActivity
        try {
            val button = activity.findViewById<Button>(FixtureContract.BUTTON_ID)
            assertNotNull(button)
            instrumentation.runOnMainSync { button.performClick() }
            assertEquals(before + 1, prefs.getInt(FixtureContract.COUNTER_KEY, 0))
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    @Test fun realInstrumentedTouchEventIncrementsCounter() {
        val prefs = context.getSharedPreferences(FixtureContract.COUNTER_PREFS, 0)
        val before = prefs.getInt(FixtureContract.COUNTER_KEY, 0)
        val intent = Intent(context, FixtureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val activity = instrumentation.startActivitySync(intent) as FixtureActivity
        try {
            instrumentation.waitForIdleSync()
            val button = activity.findViewById<Button>(FixtureContract.BUTTON_ID)
            val location = IntArray(2)
            instrumentation.runOnMainSync { button.getLocationOnScreen(location) }
            val x = (location[0] + button.width / 2).toFloat()
            val y = (location[1] + button.height / 2).toFloat()
            val at = android.os.SystemClock.uptimeMillis()
            val down = android.view.MotionEvent.obtain(
                at, at, android.view.MotionEvent.ACTION_DOWN, x, y, 0
            )
            val up = android.view.MotionEvent.obtain(
                at, at + 85, android.view.MotionEvent.ACTION_UP, x, y, 0
            )
            try {
                instrumentation.setInTouchMode(true)
                instrumentation.sendPointerSync(down)
                Thread.sleep(120)
                instrumentation.sendPointerSync(up)
                instrumentation.waitForIdleSync()
                assertEquals(before + 1, prefs.getInt(FixtureContract.COUNTER_KEY, 0))
            } finally {
                down.recycle()
                up.recycle()
            }
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    @Test fun screenRendersPinnedThreeColorPattern() {
        val visual = FixtureVisualSurface(context)
        visual.measure(
            android.view.View.MeasureSpec.makeMeasureSpec(500, android.view.View.MeasureSpec.EXACTLY),
            android.view.View.MeasureSpec.makeMeasureSpec(400, android.view.View.MeasureSpec.EXACTLY)
        )
        visual.layout(0, 0, 500, 400)
        val bitmap = Bitmap.createBitmap(500, 400, Bitmap.Config.ARGB_8888)
        visual.draw(Canvas(bitmap))
        assertEquals(FixtureContract.MAIN_COLOR, bitmap.getPixel(5, 5))
        assertEquals(FixtureContract.RED_COLOR, bitmap.getPixel(85, 110))
        assertEquals(FixtureContract.GREEN_COLOR, bitmap.getPixel(255, 110))
        assertEquals(FixtureContract.BLUE_COLOR, bitmap.getPixel(400, 110))
        bitmap.recycle()
    }

    @Test fun documentsProviderHonorsNarrowProjections() {
        val provider = fixtureProvider()
        provider.queryRoots(arrayOf(DocumentsContract.Root.COLUMN_TITLE)).use {
            assertEquals(1, it.count)
            assertTrue(it.moveToFirst())
            assertEquals("MCP V3 Fixture Docs", it.getString(0))
        }
        provider.queryDocument(
            FixtureContract.KNOWN_ID,
            arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
        ).use {
            assertEquals(1, it.count)
            assertTrue(it.moveToFirst())
            assertEquals(FixtureContract.FILE_NAME, it.getString(0))
        }
    }

    @Test fun cancelledDocumentReadIsRejectedBeforePipeCreated() {
        val provider = fixtureProvider()
        val cancelled = android.os.CancellationSignal().also { it.cancel() }
        try {
            provider.openDocument(FixtureContract.KNOWN_ID, "r", cancelled)
            fail("Pre-cancelled SAF read must abort")
        } catch (_: android.os.OperationCanceledException) {}
    }

    private fun fixtureProvider(): FixtureDocumentsProvider {
        val provider = FixtureDocumentsProvider()
        val info = android.content.pm.ProviderInfo().apply {
            authority = FixtureContract.DOCUMENT_AUTHORITY
            exported = true
            grantUriPermissions = true
            readPermission = android.Manifest.permission.MANAGE_DOCUMENTS
            writePermission = android.Manifest.permission.MANAGE_DOCUMENTS
        }
        provider.attachInfo(context, info)
        return provider
    }

    @Test fun contentProviderIsReadOnlyAndHandlesWrongIdentity() {
        val provider = fixtureProvider()
        val rows = provider.queryChildDocuments(FixtureContract.ROOT_ID, null, null as String?)
        rows.use {
            assertEquals(1, it.count)
            assertTrue(it.moveToFirst())
            val id = it.getString(it.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DOCUMENT_ID))
            assertEquals(FixtureContract.KNOWN_ID, id)
        }
        provider.openDocument(FixtureContract.KNOWN_ID, "r", null).use { read ->
            android.os.ParcelFileDescriptor.AutoCloseInputStream(read).use {
                assertArrayEquals(FixtureContract.knownBytes(), it.readBytes())
            }
        }
        try {
            provider.openDocument("wrong-id", "r", null)
            fail("Unknown file must not be openable")
        } catch (_: java.io.FileNotFoundException) {}
        try {
            provider.openDocument(FixtureContract.KNOWN_ID, "w", null)
            fail("Fixture document must remain read-only")
        } catch (_: java.io.FileNotFoundException) {}
    }
}

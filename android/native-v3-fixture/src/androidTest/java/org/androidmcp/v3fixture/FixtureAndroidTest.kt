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

    @Test fun secureActivityMustSetActualAndroidFlagAndMaskPassword() {
        val intent = Intent(context, SecureFixtureActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val activity = instrumentation.startActivitySync(intent) as SecureFixtureActivity
        try {
            instrumentation.waitForIdleSync()
            assertTrue(
                "Android must enforce screenshot/MediaProjection secure-window exclusion",
                activity.window.attributes.flags and
                    android.view.WindowManager.LayoutParams.FLAG_SECURE != 0
            )
            val input = activity.findViewById<android.widget.EditText>(
                FixtureContract.SECURE_PASSWORD_ID
            )
            assertNotNull(input)
            instrumentation.runOnMainSync {
                input.setText(FixtureContract.SYNTHETIC_SECRET)
            }
            assertTrue(
                "Actual EditText must expose TYPE_TEXT_VARIATION_PASSWORD",
                input.inputType and android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD != 0
            )
            assertTrue(
                "Accessibility must classify EditText as a password node",
                input.createAccessibilityNodeInfo().isPassword
            )
            val rootNode = instrumentation.uiAutomation.rootInActiveWindow
            // Android 16 may deliberately withhold a FLAG_SECURE window from
            // UiAutomation entirely. In that case the direct Android node
            // classification above still must report isPassword=true.
            val passwordNodes = mutableListOf<android.view.accessibility.AccessibilityNodeInfo>()
            fun collect(node: android.view.accessibility.AccessibilityNodeInfo?) {
                if (node == null) return
                if (node.contentDescription?.toString() == "android-mcp-v3-synthetic-password") {
                    passwordNodes.add(node)
                }
                for (index in 0 until node.childCount) collect(node.getChild(index))
            }
            collect(rootNode)
            if (rootNode != null) {
                assertFalse(
                    "Accessible secure window must not reveal the raw synthetic secret",
                    rootNode.text?.toString()?.contains(FixtureContract.SYNTHETIC_SECRET) == true
                )
                assertTrue(
                    "Secure window accessibility must be withheld or contain a password node",
                    passwordNodes.isNotEmpty() || rootNode.childCount == 0
                )
            }
            for (node in passwordNodes) {
                assertTrue("Android must classify this field as password", node.isPassword)
                assertFalse(
                    "Synthetic confidential fixture text leaked via accessibility",
                    node.text?.toString()?.contains(FixtureContract.SYNTHETIC_SECRET) == true
                )
            }
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    @Test fun secureSurfaceMustBeKnownColorButAbsentFromSystemScreenshot() {
        val activity = instrumentation.startActivitySync(
            Intent(context, SecureFixtureActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ) as SecureFixtureActivity
        try {
            instrumentation.waitForIdleSync()
            val canvasView = activity.findViewById<SecureFixtureSurface>(
                FixtureContract.SECURE_SURFACE_ID
            )
            assertNotNull(canvasView)
            val buffer = Bitmap.createBitmap(240, 240, Bitmap.Config.ARGB_8888)
            instrumentation.runOnMainSync {
                canvasView.measure(
                    android.view.View.MeasureSpec.makeMeasureSpec(240, android.view.View.MeasureSpec.EXACTLY),
                    android.view.View.MeasureSpec.makeMeasureSpec(240, android.view.View.MeasureSpec.EXACTLY)
                )
                canvasView.layout(0, 0, 240, 240)
                canvasView.draw(Canvas(buffer))
            }
            assertEquals(
                "Secure marker must really be rendered within the fixture process",
                FixtureContract.SECURE_MARKER_COLOR,
                buffer.getPixel(120, 120)
            )
            buffer.recycle()
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            if (screenshot != null) {
                try {
                    val x = screenshot.width / 2
                    val y = screenshot.height * 7 / 10
                    assertNotEquals(
                        "Protected window pixel leaked into real Android screenshot",
                        FixtureContract.SECURE_MARKER_COLOR,
                        screenshot.getPixel(x, y)
                    )
                } finally {
                    screenshot.recycle()
                }
            }
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    @Test fun secureActivityMustNeverBeExportedToOtherApps() {
        val information = context.packageManager.getActivityInfo(
            android.content.ComponentName(context, SecureFixtureActivity::class.java), 0
        )
        assertFalse(
            "Password-bearing fixture Activity must not be exported",
            information.exported
        )
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

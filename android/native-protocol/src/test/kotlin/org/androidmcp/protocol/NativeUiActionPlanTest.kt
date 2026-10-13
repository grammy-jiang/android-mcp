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

class NativeUiActionPlanTest {
    private val epoch = "fake-window-epoch"
    private val window = "a".repeat(32)
    private val node = "b".repeat(32)
    private fun env(api: Int = 36) = UiActionEnvironment(
        api, window, epoch, 0, 1080, 1920,
        true, true, true, true, true,
        currentNodeHandles = setOf(node),
    )
    private fun tap() = UiActionIntent(UiActionKind.TAP, window, epoch, node, 0, x = 50, y = 80)
    private fun swipe() = UiActionIntent(
        UiActionKind.SWIPE, window, epoch, node, 0,
        x = 10, y = 10, endX = 600, endY = 1600, durationMs = 500,
    )
    private fun scroll() = UiActionIntent(
        UiActionKind.SCROLL, window, epoch, node, 0,
        direction = UiScrollDirection.DOWN, steps = 3,
    )
    private fun key() = UiActionIntent(
        UiActionKind.KEY, window, epoch, node, 0, key = UiAllowedKey.ENTER,
    )

    @Test
    fun tN4A01TypedTapSwipeScrollKeyPlansAreDeterministicAndWindowBound() {
        val plans = listOf(tap(), swipe(), scroll(), key()).map {
            NativeUiActionPlans.resolve(it, env())
        }
        assertTrue(plans.all { it.state == UiActionPlanState.PLAN_ONLY })
        assertTrue(plans.all { it.requiresFreshAuthorization })
        assertTrue(plans.all { !it.idempotent })
        assertTrue(plans.all { it.digest!!.matches(Regex("[a-f0-9]{64}")) })
        assertEquals(4, plans.map { it.digest }.toSet().size)
        assertEquals(plans[0], NativeUiActionPlans.resolve(tap(), env()))
        val json = Json.parseToJsonElement(plans[0].encode()).jsonObject
        assertEquals("plan_only", json.getValue("status").jsonPrimitive.content)
        assertEquals("false", json.getValue("executed").jsonPrimitive.content)
    }

    @Test
    fun tN4A02OutOfRangeRotationUnknownActionAndShellTextAreDenied() {
        val invalid = listOf(
            tap().copy(x = -1), tap().copy(x = 1080), tap().copy(y = 1920),
            swipe().copy(endX = 99999), swipe().copy(durationMs = -1),
            swipe().copy(durationMs = 20001),
            scroll().copy(steps = 0), scroll().copy(steps = 200),
            tap().copy(rotation = 1),
            tap().copy(shellText = "input tap 100 200"),
            tap().copy(shellText = "rm -rf /"),
            key().copy(x = 100),
            scroll().copy(endX = 100),
            tap().copy(direction = UiScrollDirection.UP),
        )
        for (candidate in invalid) {
            val plan = NativeUiActionPlans.resolve(candidate, env())
            assertFalse(plan.state == UiActionPlanState.PLAN_ONLY)
            assertNull(plan.digest)
        }
        assertEquals(UiActionPlanState.ROTATION_MISMATCH,
            NativeUiActionPlans.resolve(tap().copy(rotation = 1), env()).state)
    }

    @Test
    fun tN4A03StaleNodeWindowNoAccessibilityLockedOrCallerDenied() {
        val cases = listOf(
            tap().copy(nodeEpoch = "stale") to env(),
            tap().copy(windowHandle = "c".repeat(32)) to env(),
            tap() to env().copy(fakeAccessibilityAvailable = false),
            tap() to env().copy(fakeCallerAuthenticated = false),
            tap() to env().copy(fakeUserApproval = false),
            tap() to env().copy(screenUnlocked = false),
            tap() to env().copy(foreground = false),
            tap() to env().copy(apiLevel = 29),
        )
        for ((intent, context) in cases) {
            val plan = NativeUiActionPlans.resolve(intent, context)
            assertFalse(plan.state == UiActionPlanState.PLAN_ONLY)
            assertNull(plan.digest)
        }
    }

    @Test
    fun tN4A04DuplicateDigestDoesNotImplyIdempotentOrReplayableInput() {
        val original = NativeUiActionPlans.resolve(swipe(), env())
        assertEquals(original.digest, NativeUiActionPlans.resolve(swipe(), env()).digest)
        assertFalse(original.idempotent)
        assertTrue(original.requiresFreshAuthorization)
        val rotated = NativeUiActionPlans.resolve(swipe().copy(rotation = 1), env().copy(currentRotation = 1))
        assertEquals(UiActionPlanState.PLAN_ONLY, rotated.state)
        assertNotEquals(original.digest, rotated.digest)
        val nextWindow = NativeUiActionPlans.resolve(
            swipe().copy(windowHandle = "c".repeat(32)),
            env().copy(focusedWindowHandle = "c".repeat(32)),
        )
        assertNotEquals(original.digest, nextWindow.digest)
    }

    @Test
    fun tN4A05CancelBeforeDispatchIsZeroAndAfterFakeDispatchIsUncertain() {
        val plan = NativeUiActionPlans.resolve(tap(), env())
        val before = NativeUiActionLifecycle(plan)
        assertEquals(UiActionPlanState.CANCELLED, before.cancel())
        assertEquals(0, before.realDispatchCount())
        val after = NativeUiActionLifecycle(plan)
        after.markFakeDispatchStarted()
        assertEquals(UiActionPlanState.UNCERTAIN, after.cancel())
        assertEquals(0, after.realDispatchCount())
        assertEquals(UiActionPlanState.UNCERTAIN, after.cancel())
    }

    @Test
    fun tN4A06PublicUnpairedMcpNeverExecutesOrExposesAnyUiGesture() {
        val planned = NativeUiActionPlans.resolve(key(), env())
        assertEquals(UiActionPlanState.PLAN_ONLY, planned.state)
        assertFalse(planned.idempotent)
        assertTrue(planned.requiresFreshAuthorization)
        assertTrue(planned.encode().contains("executed"))
        assertFalse(planned.encode().contains("shell"))
        assertFalse(planned.encode().contains("input keyevent"))
        val guard = NativeLocalCallerGuard()
        val spoof = SyntheticCallerApproval(guard.epoch, "fake", true)
        assertFalse(guard.authorizeSensitive(LocalHttpRequest(), "native_tap", spoof).allowed)
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
    }

    @Test
    fun forgedNodeHandleOrOldWindowHierarchyFailsClosed() {
        val context = env()
        assertEquals(UiActionPlanState.STALE, NativeUiActionPlans.resolve(
            tap().copy(nodeHandle = "c".repeat(32)), context,
        ).state)
        assertEquals(UiActionPlanState.STALE, NativeUiActionPlans.resolve(
            tap(), context.copy(currentNodeHandles = emptySet()),
        ).state)
        val rotated = context.copy(nodeEpoch = "next-window-epoch")
        assertEquals(UiActionPlanState.STALE,
            NativeUiActionPlans.resolve(tap(), rotated).state)
        val unchanged = NativeUiActionPlans.resolve(tap(), env())
        assertEquals(UiActionPlanState.PLAN_ONLY, unchanged.state)
        assertFalse(unchanged.idempotent)
    }

    @Test
    fun cancellationBeforeFakeDispatchCannotBeReopenedForReplay() {
        val plan = NativeUiActionPlans.resolve(tap(), env())
        val cancelled = NativeUiActionLifecycle(plan)
        assertEquals(UiActionPlanState.CANCELLED, cancelled.cancel())
        cancelled.markFakeDispatchStarted()
        assertEquals(UiActionPlanState.CANCELLED, cancelled.cancel())
        assertEquals(0, cancelled.realDispatchCount())
        assertFalse(plan.encode().contains("input tap"))
    }
}

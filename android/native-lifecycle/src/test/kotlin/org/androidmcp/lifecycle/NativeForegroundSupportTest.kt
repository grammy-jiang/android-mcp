package org.androidmcp.lifecycle

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeForegroundSupportTest {
    @Test
    fun androidElevenThroughThirteenDoNotEnableN3ForegroundMode() {
        for (api in 30..33) {
            assertFalse(NativeForegroundSupport.supported(api))
        }
    }

    @Test
    fun androidFourteenAndNewerEnableN3ForegroundMode() {
        for (api in 34..36) {
            assertTrue(NativeForegroundSupport.supported(api))
        }
    }

    @Test
    fun invalidApiLevelsDoNotEnableN3ForegroundMode() {
        for (api in listOf(-1, 0, 1, 29)) {
            assertFalse(NativeForegroundSupport.supported(api))
        }
    }
}

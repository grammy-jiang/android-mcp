package org.androidmcp.protocol

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class NativeMutationProfileTest {
    private val digestA = "a".repeat(64)
    private fun attempt(policy: NativeMutationPolicy,
                        action: NativeMutationOperation = NativeMutationOperation.UI_GESTURE,
                        digest: String = digestA): SyntheticMutationAttempt =
        SyntheticMutationAttempt(
            action, policy.processEpoch, "request-00001", digest,
            modelApproved = true, fakeCallerVerified = true,
            fakeSignedActionFresh = true, fakeLeasePresent = true,
            fakeRuntimeConsent = true,
        )

    @Test
    fun tN6E01DefaultLiveKotlinCatalogContainsNoMutationTool() {
        val policy = NativeMutationPolicy()
        assertEquals(listOf("device_status"), NativeToolProfiles().liveTools(true).map { it.name })
        assertTrue(policy.publicMutatingTools().isEmpty())
        assertFalse(policy.realMutationAllowed())
    }

    @Test
    fun tN6E02ModelApprovalAndFakeSignedOrStaleGrantNeverBypassSecurity() {
        val policy = NativeMutationPolicy()
        val validFake = attempt(policy)
        assertEquals(NativeMutationStatus.UNAUTHENTICATED,
            policy.evaluate(validFake.copy(fakeCallerVerified = false)).status)
        assertEquals(NativeMutationStatus.UNAUTHENTICATED,
            policy.evaluate(validFake.copy(fakeSignedActionFresh = false)).status)
        assertEquals(NativeMutationStatus.UNAUTHENTICATED,
            policy.evaluate(validFake.copy(fakeLeasePresent = false)).status)
        assertEquals(NativeMutationStatus.STALE,
            policy.evaluate(validFake.copy(processEpoch = "old-process-epoch")).status)
        assertEquals(NativeMutationStatus.DISABLED, policy.evaluate(validFake).status)
    }

    @Test
    fun tN6E03EvenSyntheticLeaseMissingRealAndroidConsentFailsClosed() {
        val policy = NativeMutationPolicy()
        for (operation in NativeMutationOperation.entries) {
            val request = attempt(policy, action = operation)
            assertEquals(NativeMutationStatus.CONSENT_REQUIRED,
                policy.evaluate(request.copy(fakeRuntimeConsent = false)).status)
            assertEquals(NativeMutationStatus.DISABLED, policy.evaluate(request).status)
        }
    }

    @Test
    fun tN6E04DisabledHighRiskMetadataHonestNonIdempotentAndPotentiallyDestructive() {
        val policy = NativeMutationPolicy()
        val descriptors = policy.privateDescriptors()
        assertEquals(NativeMutationOperation.entries.toSet(), descriptors.map { it.operation }.toSet())
        descriptors.forEach { descriptor ->
            assertFalse(descriptor.enabled)
            assertFalse(descriptor.readOnly)
            assertFalse(descriptor.idempotent)
            assertTrue(descriptor.encode().contains("\"enabled\":false"))
        }
        assertTrue(descriptors.first { it.operation == NativeMutationOperation.APK_INSTALL }
            .potentiallyDestructive)
        assertTrue(descriptors.first { it.operation == NativeMutationOperation.SYSTEM_SETTING }
            .potentiallyDestructive)
    }

    @Test
    fun tN6E05AmbiguousGestureOrInstallReplayAndStopNeverDispatch() {
        val first = NativeMutationPolicy()
        val original = attempt(first)
        assertEquals(NativeMutationStatus.UNCERTAIN, first.markFakeAmbiguous(original).status)
        val retry = original.copy(requestId = "request-00002", fakeSignedActionFresh = true)
        assertEquals(NativeMutationStatus.UNCERTAIN, first.evaluate(retry).status)
        val resumed = NativeMutationPolicy(first.snapshot())
        assertEquals(NativeMutationStatus.UNCERTAIN,
            resumed.evaluate(attempt(resumed).copy(requestId = "request-00003")).status)
        resumed.stop()
        assertEquals(NativeMutationStatus.STOPPED,
            resumed.evaluate(attempt(resumed, NativeMutationOperation.APK_INSTALL,
                "b".repeat(64))).status)
        assertFalse(resumed.realMutationAllowed())
    }

    @Test
    fun tN6E06NoLiveMutatingHandlerOrHonestExecutionReceipt() {
        val policy = NativeMutationPolicy()
        val result = policy.evaluate(attempt(policy))
        assertFalse(result.mutationExecuted)
        assertTrue(result.encode().contains("\"mutation_executed\":false"))
        assertTrue(result.encode().contains("\"automatic_retry\":false"))
        assertFalse(policy.realMutationAllowed())
        assertTrue(policy.publicMutatingTools().isEmpty())
    }

    @Test
    fun invalidAndOversizedRecoveryAlwaysRemainsUncertainAndRedacted() {
        val corrupted = listOf(
            MutationDenyRecovery(listOf("not-a-digest")),
            MutationDenyRecovery(listOf(digestA, digestA)),
            MutationDenyRecovery(List(33) { "%064x".format(it + 1) }),
        )
        for (snapshot in corrupted) {
            val policy = NativeMutationPolicy(snapshot)
            assertEquals(NativeMutationStatus.UNCERTAIN,
                policy.evaluate(attempt(policy)).status)
            assertFalse(policy.realMutationAllowed())
            assertFalse(snapshot.toString().contains(digestA))
        }
    }

    @Test
    fun boundedAmbiguousTombstonesNeverEvictEarlierUncertainAction() {
        val policy = NativeMutationPolicy()
        for (i in 1..32) {
            val digest = "%064x".format(i)
            assertEquals(NativeMutationStatus.UNCERTAIN,
                policy.markFakeAmbiguous(attempt(policy, digest = digest)).status)
        }
        val oldest = "%064x".format(1)
        assertEquals(NativeMutationStatus.UNCERTAIN,
            policy.evaluate(attempt(policy, digest = oldest).copy(requestId = "retry-new-id")).status)
        assertEquals(NativeMutationStatus.DENIED,
            policy.markFakeAmbiguous(attempt(policy, digest = "f".repeat(64))).status)
        assertEquals(32, policy.snapshot().ambiguousDigests.size)
        assertFalse(policy.realMutationAllowed())
    }

    @Test
    fun malformedFutureSchemaAndEvenModelDeniedRemainNonExecuting() {
        val policy = NativeMutationPolicy()
        val requested = attempt(policy)
        assertEquals(NativeMutationStatus.UNSUPPORTED,
            policy.evaluate(requested.copy(schemaVersion = 99)).status)
        assertEquals(NativeMutationStatus.DENIED,
            policy.evaluate(requested.copy(requestId = "bogus request id")).status)
        assertEquals(NativeMutationStatus.DENIED,
            policy.evaluate(requested.copy(actionDigest = "A".repeat(64))).status)
        assertEquals(NativeMutationStatus.DISABLED,
            policy.evaluate(requested.copy(modelApproved = false)).status)
        val text = policy.evaluate(requested).encode()
        assertFalse(text.contains(digestA))
        assertFalse(text.contains("request-00001"))
        assertTrue(text.toByteArray().size < 1024)
        assertFalse(policy.realMutationAllowed())
    }
}

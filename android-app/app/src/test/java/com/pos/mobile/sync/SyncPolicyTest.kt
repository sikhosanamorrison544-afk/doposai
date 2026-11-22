package com.pos.mobile.sync

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncPolicyTest {

    @Test
    fun auth_401_never_permanently_fails() {
        assertFalse(SyncPolicy.shouldMarkFailed(401, 1, "HTTP 401"))
        assertFalse(SyncPolicy.shouldMarkFailed(401, SyncPolicy.MAX_PUSH_ATTEMPTS + 5, "HTTP 401"))
    }

    @Test
    fun forbidden_403_is_permanent_but_retains_failed_status() {
        assertTrue(SyncPolicy.shouldMarkFailed(403, 1, "Permission denied: sales"))
        assertTrue(SyncPolicy.isPermanentFailureHttp(403))
    }

    @Test
    fun server_errors_retry_until_cap() {
        assertFalse(SyncPolicy.shouldMarkFailed(503, 1, "HTTP 503"))
        assertTrue(SyncPolicy.shouldMarkFailed(503, SyncPolicy.MAX_PUSH_ATTEMPTS, "HTTP 503"))
    }

    @Test
    fun network_timeout_is_retryable() {
        assertTrue(SyncPolicy.isRetryableErrorMessage("timeout"))
        assertFalse(SyncPolicy.shouldMarkFailed(null, 1, "timeout connecting"))
    }

    @Test
    fun validation_errors_fail_quickly() {
        assertTrue(SyncPolicy.shouldMarkFailed(422, 1, "validation"))
        assertTrue(SyncPolicy.shouldMarkFailed(400, 1, "bad request"))
    }
}

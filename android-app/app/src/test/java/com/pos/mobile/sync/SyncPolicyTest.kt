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
    fun server_errors_never_permanently_fail_even_after_many_attempts() {
        assertFalse(SyncPolicy.shouldMarkFailed(503, 1, "HTTP 503"))
        assertFalse(SyncPolicy.shouldMarkFailed(503, SyncPolicy.MAX_PUSH_ATTEMPTS + 100, "HTTP 503"))
        assertFalse(SyncPolicy.shouldMarkFailed(429, 999, "HTTP 429"))
        assertFalse(SyncPolicy.shouldMarkFailed(408, 999, "HTTP 408"))
    }

    @Test
    fun network_timeout_never_permanently_fails() {
        assertTrue(SyncPolicy.isRetryableErrorMessage("timeout"))
        assertFalse(SyncPolicy.shouldMarkFailed(null, 1, "timeout connecting"))
        assertFalse(SyncPolicy.shouldMarkFailed(null, 500, "failed to connect to host"))
    }

    @Test
    fun validation_errors_fail_quickly() {
        assertTrue(SyncPolicy.shouldMarkFailed(422, 1, "validation"))
        assertTrue(SyncPolicy.shouldMarkFailed(400, 1, "bad request"))
    }

    @Test
    fun three_day_window_is_warn_not_delete() {
        assertTrue(SyncPolicy.OFFLINE_OPERATING_WINDOW_MS >= 3L * 24 * 60 * 60 * 1000)
        val created = System.currentTimeMillis() - SyncPolicy.SYNC_DEADLINE_MS - 1
        assertTrue(SyncPolicy.isPastDeadline(created))
        // Age past deadline must not imply permanent failure for network errors
        assertFalse(SyncPolicy.shouldMarkFailed(null, 50, "connection reset"))
    }
}

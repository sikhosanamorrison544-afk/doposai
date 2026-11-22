package com.pos.mobile.sync

/**
 * Offline → online delivery policy for queued POS data.
 *
 * Goal: once the device has validated internet and a valid session within
 * [SYNC_DEADLINE_MS] of enqueue, drain sales/mutations to the server.
 */
object SyncPolicy {
    /** Match SessionStore offline grace — queue must sync within this window. */
    const val SYNC_DEADLINE_MS = 3L * 24 * 60 * 60 * 1000

    /** Escalate UI / expedited work when pending rows are this old. */
    const val SYNC_WARN_AGE_MS = 2L * 24 * 60 * 60 * 1000

    /** Cap per-row attempts before marking permanently failed (non-retryable path). */
    const val MAX_PUSH_ATTEMPTS = 40

    fun ageMs(createdAt: Long, now: Long = System.currentTimeMillis()): Long =
        (now - createdAt).coerceAtLeast(0L)

    fun isPastDeadline(createdAt: Long, now: Long = System.currentTimeMillis()): Boolean =
        ageMs(createdAt, now) >= SYNC_DEADLINE_MS

    fun isAging(createdAt: Long, now: Long = System.currentTimeMillis()): Boolean =
        ageMs(createdAt, now) >= SYNC_WARN_AGE_MS

    fun isRetryableHttp(code: Int): Boolean =
        code == 401 || code == 408 || code == 429 || code >= 500

    /** Auth must never permanently drop a queued sale — refresh / re-login recovers. */
    fun isAuthHttp(code: Int): Boolean = code == 401

    /**
     * 403 = retain the queue item as failed (do not delete the local sale).
     * Validation/malformed payloads also permanent-fail so we do not spin forever.
     */
    fun isPermanentFailureHttp(code: Int): Boolean =
        code == 400 || code == 403 || code == 404 || code == 409 || code == 422

    fun isRetryableErrorMessage(message: String?): Boolean {
        val m = (message ?: "").lowercase()
        if (m.isBlank()) return true
        return m.contains("timeout") ||
            m.contains("unable to resolve") ||
            m.contains("failed to connect") ||
            m.contains("connection") ||
            m.contains("ssl") ||
            m.contains("unreachable") ||
            m.contains("network") ||
            m.contains("http 401") ||
            m.contains("http 408") ||
            m.contains("http 429") ||
            m.contains("http 5") ||
            Regex("http\\s*5\\d\\d").containsMatchIn(m)
    }

    /**
     * Decide whether a failed push should stay PENDING (retry) or become FAILED.
     * Auth failures always stay PENDING so reconnect/re-login can drain them.
     */
    fun shouldMarkFailed(
        httpCode: Int?,
        attempts: Int,
        errorMessage: String?,
    ): Boolean {
        if (httpCode != null && isAuthHttp(httpCode)) return false
        if (httpCode != null && isPermanentFailureHttp(httpCode)) return true
        if (httpCode != null && isRetryableHttp(httpCode)) {
            return attempts >= MAX_PUSH_ATTEMPTS
        }
        if (isRetryableErrorMessage(errorMessage)) {
            return attempts >= MAX_PUSH_ATTEMPTS
        }
        // Unknown / validation-style body without a clear retry signal
        return attempts >= 3
    }
}

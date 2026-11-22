package com.pos.mobile.sync

/**
 * Offline → online delivery policy for queued POS data.
 *
 * Cashiers may sell offline for at least [OFFLINE_OPERATING_WINDOW_MS] (3 days).
 * Unsynchronized sales are retained until the server acknowledges them — never
 * deleted for age. [SYNC_DEADLINE_MS] is only a warning/expedite signal.
 */
object SyncPolicy {
    /** Minimum offline operating window (match SessionStore offline grace). */
    const val OFFLINE_OPERATING_WINDOW_MS = 3L * 24 * 60 * 60 * 1000

    /** Warn / expedite WorkManager when a row is this old (not a deletion timer). */
    const val SYNC_DEADLINE_MS = OFFLINE_OPERATING_WINDOW_MS

    /** Escalate UI / expedited work when pending rows are this old. */
    const val SYNC_WARN_AGE_MS = 2L * 24 * 60 * 60 * 1000

    /**
     * Soft attempt counter for logging/backoff only.
     * Transient failures must NOT permanently fail the sale when this is exceeded.
     */
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
     * Auth / network / 5xx / 429 always stay PENDING (indefinite retention until sync).
     * Only clear permanent client/authz errors become FAILED (sale row still kept).
     */
    fun shouldMarkFailed(
        httpCode: Int?,
        attempts: Int,
        errorMessage: String?,
    ): Boolean {
        if (httpCode != null && isAuthHttp(httpCode)) return false
        if (httpCode != null && isPermanentFailureHttp(httpCode)) return true
        if (httpCode != null && isRetryableHttp(httpCode)) return false
        if (isRetryableErrorMessage(errorMessage)) return false
        // Ambiguous client errors: fail after a few attempts so we do not spin forever
        return attempts >= 3
    }
}

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

    fun isRetryableErrorMessage(message: String?): Boolean {
        val m = (message ?: "").lowercase()
        if (m.isBlank()) return true
        return m.contains("timeout") ||
            m.contains("unable to resolve") ||
            m.contains("failed to connect") ||
            m.contains("connection") ||
            m.contains("ssl") ||
            m.contains("unreachable") ||
            m.contains("http 401") ||
            m.contains("http 408") ||
            m.contains("http 429") ||
            m.contains("http 5") ||
            Regex("http\\s*5\\d\\d").containsMatchIn(m)
    }
}

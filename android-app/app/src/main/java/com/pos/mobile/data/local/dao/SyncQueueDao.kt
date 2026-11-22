package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.SyncQueueEntity

@Dao
interface SyncQueueDao {
    @Query("SELECT * FROM sync_queue WHERE status = :status ORDER BY createdAt ASC")
    suspend fun getByStatus(status: String): List<SyncQueueEntity>

    @Query("SELECT COUNT(*) FROM sync_queue WHERE status = :status")
    suspend fun countByStatus(status: String): Int

    @Query("SELECT MIN(createdAt) FROM sync_queue WHERE status = :status")
    suspend fun oldestCreatedAt(status: String): Long?

    @Insert
    suspend fun insert(entity: SyncQueueEntity): Long

    @Query("UPDATE sync_queue SET status = :status, lastError = :error WHERE id = :id")
    suspend fun updateStatus(id: Long, status: String, error: String? = null)

    @Query("UPDATE sync_queue SET retryCount = retryCount + 1, lastError = :error WHERE id = :id")
    suspend fun incrementRetry(id: Long, error: String?)

    @Query("UPDATE sync_queue SET clientSaleUuid = :uuid WHERE id = :id")
    suspend fun setClientSaleUuid(id: Long, uuid: String)

    @Query(
        """
        UPDATE sync_queue SET status = 'pending', lastError = NULL
        WHERE status = 'failed' AND retryCount < :maxRetries
        """,
    )
    suspend fun requeueRetriableFailed(maxRetries: Int): Int

    /**
     * Re-open failed rows that are not permanent client/authz errors so a long
     * offline period + many retries never leaves recoverable sales stuck.
     */
    @Query(
        """
        UPDATE sync_queue SET status = 'pending'
        WHERE status = 'failed'
          AND (
            lastError IS NULL
            OR (
              lower(lastError) NOT LIKE '%permission denied%'
              AND lower(lastError) NOT LIKE '%http 400%'
              AND lower(lastError) NOT LIKE '%http 403%'
              AND lower(lastError) NOT LIKE '%http 404%'
              AND lower(lastError) NOT LIKE '%http 409%'
              AND lower(lastError) NOT LIKE '%http 422%'
            )
          )
        """,
    )
    suspend fun requeueRecoverableFailed(): Int

    /**
     * Recover rows left in `syncing` after a crash/kill mid-POST.
     * Drain only loads `pending`, so orphaned syncing sales never uploaded
     * (and never deducted server stock) until reset.
     */
    @Query(
        """
        UPDATE sync_queue SET status = 'pending'
        WHERE status = 'syncing'
        """,
    )
    suspend fun requeueOrphanedSyncing(): Int

    @Query(
        """
        SELECT COUNT(*) FROM sync_queue
        WHERE status IN ('pending', 'syncing')
        """,
    )
    suspend fun countOpenUploads(): Int

    @Query("DELETE FROM sync_queue WHERE status = :status")
    suspend fun deleteByStatus(status: String)

    @Query("DELETE FROM sync_queue WHERE status = 'synced' AND createdAt < :olderThanMs")
    suspend fun pruneSyncedOlderThan(olderThanMs: Long)
}

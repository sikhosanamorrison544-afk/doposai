package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.SyncQueueEntity

@Dao
interface SyncQueueDao {
    @Query("SELECT * FROM sync_queue WHERE status = :status ORDER BY createdAt ASC")
    suspend fun getByStatus(status: String): List<SyncQueueEntity>

    @Insert
    suspend fun insert(entity: SyncQueueEntity): Long

    @Query("UPDATE sync_queue SET status = :status, lastError = :error WHERE id = :id")
    suspend fun updateStatus(id: Long, status: String, error: String? = null)

    @Query("UPDATE sync_queue SET retryCount = retryCount + 1, lastError = :error WHERE id = :id")
    suspend fun incrementRetry(id: Long, error: String?)

    @Query("DELETE FROM sync_queue WHERE status = :status")
    suspend fun deleteByStatus(status: String)
}

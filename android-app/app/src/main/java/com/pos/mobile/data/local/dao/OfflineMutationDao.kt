package com.pos.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import com.pos.mobile.data.local.entity.OfflineMutationEntity

@Dao
interface OfflineMutationDao {
    @Query("SELECT * FROM offline_mutations WHERE status = :status ORDER BY createdAt ASC")
    suspend fun getByStatus(status: String): List<OfflineMutationEntity>

    @Insert
    suspend fun insert(entity: OfflineMutationEntity): Long

    @Query("UPDATE offline_mutations SET status = :status, error = :error WHERE id = :id")
    suspend fun updateStatus(id: Long, status: String, error: String?)

    @Query("SELECT COUNT(*) FROM offline_mutations WHERE status = :status")
    suspend fun countByStatus(status: String): Int
}

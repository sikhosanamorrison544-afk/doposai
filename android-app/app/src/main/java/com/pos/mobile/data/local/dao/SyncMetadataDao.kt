package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.SyncMetadataEntity

@Dao
interface SyncMetadataDao {
    @Query("SELECT * FROM sync_metadata WHERE key = :key")
    suspend fun get(key: String): SyncMetadataEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(entity: SyncMetadataEntity)

    @Query("UPDATE sync_metadata SET lastSyncedAt = :at, lastSyncSuccess = :success WHERE key = :key")
    suspend fun updateLastSynced(key: String, at: Long, success: Boolean)
}

package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.SaleEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface SaleDao {
    @Query("SELECT * FROM sales ORDER BY createdAt DESC")
    fun getAll(): Flow<List<SaleEntity>>

    @Query("SELECT * FROM sales WHERE localId = :localId")
    suspend fun getByLocalId(localId: Long): SaleEntity?

    @Insert
    suspend fun insert(sale: SaleEntity): Long

    @Query("UPDATE sales SET serverId = :serverId, syncedAt = :syncedAt WHERE localId = :localId")
    suspend fun markSynced(localId: Long, serverId: Int, syncedAt: Long)
}

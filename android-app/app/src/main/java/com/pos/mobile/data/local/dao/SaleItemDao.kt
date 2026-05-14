package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.SaleItemEntity

@Dao
interface SaleItemDao {
    @Query("SELECT * FROM sale_items WHERE saleLocalId = :saleLocalId")
    suspend fun getBySaleLocalId(saleLocalId: Long): List<SaleItemEntity>

    @Insert
    suspend fun insertAll(items: List<SaleItemEntity>)
}

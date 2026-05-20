package com.pos.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.pos.mobile.data.local.entity.SupplierEntity

@Dao
interface SupplierDao {
    @Query("SELECT * FROM suppliers ORDER BY businessName")
    suspend fun getAll(): List<SupplierEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(entities: List<SupplierEntity>)

    @Query("DELETE FROM suppliers")
    suspend fun deleteAll()
}

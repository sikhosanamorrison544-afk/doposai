package com.pos.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.pos.mobile.data.local.entity.BranchEntity

@Dao
interface BranchDao {
    @Query("SELECT * FROM branches ORDER BY name")
    suspend fun getAll(): List<BranchEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(entities: List<BranchEntity>)

    @Query("DELETE FROM branches")
    suspend fun deleteAll()
}

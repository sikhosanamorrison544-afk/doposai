package com.pos.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.pos.mobile.data.local.entity.EnterpriseCacheEntity

@Dao
interface EnterpriseCacheDao {
    @Query("SELECT * FROM enterprise_cache WHERE cacheKey = :key LIMIT 1")
    suspend fun get(key: String): EnterpriseCacheEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(entity: EnterpriseCacheEntity)
}

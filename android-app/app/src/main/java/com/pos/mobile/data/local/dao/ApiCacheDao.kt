package com.pos.mobile.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.pos.mobile.data.local.entity.ApiCacheEntity

@Dao
interface ApiCacheDao {
    @Query("SELECT * FROM api_cache WHERE cacheKey = :key LIMIT 1")
    suspend fun get(key: String): ApiCacheEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(entity: ApiCacheEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAll(entities: List<ApiCacheEntity>)

    @Query("DELETE FROM api_cache")
    suspend fun deleteAll()

    @Query("SELECT COUNT(*) FROM api_cache")
    suspend fun count(): Int
}

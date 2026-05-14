package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.ProductEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface ProductDao {
    @Query("SELECT * FROM products WHERE isActive = 1 ORDER BY name")
    fun getAllActive(): Flow<List<ProductEntity>>

    @Query("SELECT COUNT(*) FROM products WHERE isActive = 1")
    suspend fun countActive(): Int

    @Query("SELECT * FROM products WHERE id = :id")
    suspend fun getById(id: Int): ProductEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(products: List<ProductEntity>)

    @Query("DELETE FROM products")
    suspend fun deleteAll()
}

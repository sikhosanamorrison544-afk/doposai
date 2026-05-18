package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.ProductEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface ProductDao {
    @Query("SELECT * FROM products WHERE isActive = 1 ORDER BY name")
    fun getAllActive(): Flow<List<ProductEntity>>

    @Query("SELECT * FROM products WHERE isActive = 1 ORDER BY name")
    suspend fun getAllActiveList(): List<ProductEntity>

    @Query("SELECT COUNT(*) FROM products WHERE isActive = 1")
    suspend fun countActive(): Int

    @Query("SELECT * FROM products WHERE id = :id")
    suspend fun getById(id: Int): ProductEntity?

    @Query(
        "SELECT * FROM products WHERE isActive = 1 AND " +
            "(LOWER(name) LIKE :pattern OR LOWER(IFNULL(barcode, '')) LIKE :pattern) " +
            "ORDER BY name LIMIT 30"
    )
    suspend fun searchActive(pattern: String): List<ProductEntity>

    /** Fallback when isActive flag was not stored correctly during an older sync. */
    @Query(
        "SELECT * FROM products WHERE " +
            "(LOWER(name) LIKE :pattern OR LOWER(IFNULL(barcode, '')) LIKE :pattern) " +
            "ORDER BY name LIMIT 30"
    )
    suspend fun searchAny(pattern: String): List<ProductEntity>

    @Query("SELECT * FROM products WHERE isActive = 1 AND UPPER(barcode) = UPPER(:barcode) LIMIT 1")
    suspend fun findByBarcode(barcode: String): ProductEntity?

    @Query("SELECT * FROM products WHERE UPPER(barcode) = UPPER(:barcode) LIMIT 1")
    suspend fun findByBarcodeAny(barcode: String): ProductEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(products: List<ProductEntity>)

    @Query("UPDATE products SET stockQty = stockQty - :qty WHERE id = :productId")
    suspend fun deductStock(productId: Int, qty: Double)

    @Query("DELETE FROM products")
    suspend fun deleteAll()
}

package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "products")
data class ProductEntity(
    @PrimaryKey val id: Int,
    val name: String,
    val barcode: String?,
    val categoryId: Int?,
    val stockQty: Double,
    val sellingPrice: Double,
    val costPrice: Double,
    val isActive: Boolean,
    val serverSyncedAt: Long? = null
)

package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "sale_items",
    foreignKeys = [
        ForeignKey(
            entity = SaleEntity::class,
            parentColumns = ["localId"],
            childColumns = ["saleLocalId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("saleLocalId")]
)
data class SaleItemEntity(
    @PrimaryKey(autoGenerate = true) val localId: Long = 0,
    val saleLocalId: Long,
    val productId: Int,
    val quantity: Int,
    val unitPrice: Double,
    val discount: Double,
    val lineTotal: Double
)

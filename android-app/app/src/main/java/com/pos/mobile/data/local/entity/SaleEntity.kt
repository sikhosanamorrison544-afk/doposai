package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "sales")
data class SaleEntity(
    @PrimaryKey(autoGenerate = true) val localId: Long = 0,
    val serverId: Int? = null,
    val cashierId: Int,
    val customerId: Int?,
    val subtotal: Double,
    val discountTotal: Double,
    val total: Double,
    val notes: String?,
    val collectionStatus: String,
    val createdAt: Long,
    val syncedAt: Long? = null
)

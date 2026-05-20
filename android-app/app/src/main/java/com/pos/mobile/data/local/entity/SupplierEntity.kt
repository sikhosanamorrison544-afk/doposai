package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "suppliers")
data class SupplierEntity(
    @PrimaryKey val id: Int,
    val businessName: String,
    val phone: String?,
    val whatsappNumber: String?,
    val balance: Double,
    val serverSyncedAt: Long,
)

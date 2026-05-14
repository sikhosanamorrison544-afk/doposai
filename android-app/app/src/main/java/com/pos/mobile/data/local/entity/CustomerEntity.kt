package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "customers")
data class CustomerEntity(
    @PrimaryKey val id: Int,
    val name: String,
    val phone: String?,
    val email: String?,
    val serverSyncedAt: Long? = null
)

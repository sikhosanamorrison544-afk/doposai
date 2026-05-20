package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "branches")
data class BranchEntity(
    @PrimaryKey val id: Int,
    val name: String,
    val code: String?,
    val isDefault: Boolean,
    val serverSyncedAt: Long,
)

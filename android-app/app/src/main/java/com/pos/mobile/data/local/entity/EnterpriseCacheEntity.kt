package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/** Cached JSON blob for enterprise offline (open POs, reorder list, etc.). */
@Entity(tableName = "enterprise_cache")
data class EnterpriseCacheEntity(
    @PrimaryKey val cacheKey: String,
    val jsonBody: String,
    val syncedAt: Long,
)

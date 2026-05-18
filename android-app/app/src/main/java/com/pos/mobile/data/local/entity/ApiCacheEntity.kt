package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Snapshot of a GET response from the Render master API for offline WebView / fetch.
 */
@Entity(tableName = "api_cache")
data class ApiCacheEntity(
    @PrimaryKey val cacheKey: String,
    val responseBody: String,
    val contentType: String,
    val statusCode: Int,
    val syncedAt: Long,
)

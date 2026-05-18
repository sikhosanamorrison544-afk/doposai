package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Stores last_synced_at timestamps per entity type.
 * UI and sync logic use this to know when data was last pulled from the server.
 */
@Entity(tableName = "sync_metadata")
data class SyncMetadataEntity(
    @PrimaryKey val key: String,
    val lastSyncedAt: Long,
    val lastSyncSuccess: Boolean = true
) {
    companion object {
        const val KEY_PRODUCTS = "products"
        const val KEY_CATEGORIES = "categories"
        const val KEY_CUSTOMERS = "customers"
        const val KEY_SALES_PUSH = "sales_push"
        const val KEY_MASTER_CACHE = "master_cache"
    }
}

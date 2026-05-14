package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Queue table for unsynced transactions.
 * When a sale is created offline, it is written to sales/sale_items/payments
 * and a row is added here. The sync worker processes this table and POSTs to the API.
 */
@Entity(tableName = "sync_queue")
data class SyncQueueEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val saleLocalId: Long,
    val createdAt: Long,
    val retryCount: Int = 0,
    val lastError: String? = null,
    val status: String = STATUS_PENDING
) {
    companion object {
        const val STATUS_PENDING = "pending"
        const val STATUS_SYNCING = "syncing"
        const val STATUS_SYNCED = "synced"
        const val STATUS_FAILED = "failed"
    }
}

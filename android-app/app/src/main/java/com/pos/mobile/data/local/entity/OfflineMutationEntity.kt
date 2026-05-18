package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/** Queued API write (POST/PUT) made while offline; replayed when online. */
@Entity(tableName = "offline_mutations")
data class OfflineMutationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val method: String,
    val path: String,
    val requestBody: String?,
    val contentType: String?,
    val createdAt: Long,
    val status: String = STATUS_PENDING,
    val error: String? = null,
) {
    companion object {
        const val STATUS_PENDING = "pending"
        const val STATUS_SYNCED = "synced"
        const val STATUS_FAILED = "failed"
    }
}

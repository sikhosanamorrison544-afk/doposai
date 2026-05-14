package com.pos.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "payments",
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
data class PaymentEntity(
    @PrimaryKey(autoGenerate = true) val localId: Long = 0,
    val saleLocalId: Long,
    val method: String,
    val amount: Double
)

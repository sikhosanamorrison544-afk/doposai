package com.pos.mobile.data.local.dao

import androidx.room.*
import com.pos.mobile.data.local.entity.PaymentEntity

@Dao
interface PaymentDao {
    @Query("SELECT * FROM payments WHERE saleLocalId = :saleLocalId")
    suspend fun getBySaleLocalId(saleLocalId: Long): List<PaymentEntity>

    @Insert
    suspend fun insertAll(payments: List<PaymentEntity>)
}

package com.pos.mobile.sync

import android.util.Log

/**
 * Safe diagnostic logging for offline sale upload.
 * Never logs passwords, JWTs, Authorization headers, or payment secrets.
 */
object SaleSyncLog {
    private const val TAG = "SALE_SYNC"

    fun event(
        clientSaleId: String?,
        queueId: Long? = null,
        status: String? = null,
        attempt: Int? = null,
        endpoint: String? = null,
        result: String? = null,
        action: String? = null,
        serverSaleId: Int? = null,
        httpStatus: Int? = null,
    ) {
        val parts = mutableListOf<String>()
        if (!clientSaleId.isNullOrBlank()) parts += "client_sale_id=$clientSaleId"
        if (queueId != null) parts += "queue_id=$queueId"
        if (!status.isNullOrBlank()) parts += "status=$status"
        if (attempt != null) parts += "attempt=$attempt"
        if (!endpoint.isNullOrBlank()) parts += "endpoint=$endpoint"
        if (httpStatus != null) parts += "http=$httpStatus"
        if (!result.isNullOrBlank()) parts += "result=$result"
        if (!action.isNullOrBlank()) parts += "action=$action"
        if (serverSaleId != null) parts += "server_sale_id=$serverSaleId"
        Log.i(TAG, parts.joinToString(" "))
    }
}

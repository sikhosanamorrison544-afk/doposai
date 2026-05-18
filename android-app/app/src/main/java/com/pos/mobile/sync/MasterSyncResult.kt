package com.pos.mobile.sync

data class MasterSyncResult(
    val apiEndpointsCached: Int,
    val apiEndpointsFailed: Int,
    val webPagesCached: Int,
    val laybyPaymentCaches: Int,
)

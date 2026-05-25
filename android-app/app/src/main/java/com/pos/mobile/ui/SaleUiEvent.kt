package com.pos.mobile.ui

/** One-shot checkout result for UI (Toast, print, dismiss sheet). */
sealed class SaleUiEvent {
    data class Success(
        val message: String,
        val receipt: ReceiptPrinter.SaleReceiptRequest?,
        /** Server sale id (for refunds); null if not synced yet. */
        val serverSaleId: Int? = null,
        val saleLocalId: Long = 0L,
    ) : SaleUiEvent()

    data class Failed(val message: String) : SaleUiEvent()
}

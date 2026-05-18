package com.pos.mobile.ui

/** One-shot checkout result for UI (Toast, print, dismiss sheet). */
sealed class SaleUiEvent {
    data class Success(
        val message: String,
        val receipt: ReceiptPrinter.SaleReceiptRequest?,
    ) : SaleUiEvent()

    data class Failed(val message: String) : SaleUiEvent()
}

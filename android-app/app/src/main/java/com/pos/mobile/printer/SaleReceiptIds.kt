package com.pos.mobile.printer

/**
 * Sale identifiers printed on every transaction receipt (refunds use server [saleId]).
 */
object SaleReceiptIds {

    /** Lines to print on thermal / system receipts (never empty when [saleLocalId] > 0). */
    fun lines(saleId: Int?, saleLocalId: Long?): List<String> {
        val out = mutableListOf<String>()
        if (saleId != null && saleId > 0) {
            out.add("SALE ID: $saleId")
        }
        if (saleLocalId != null && saleLocalId > 0) {
            if (saleId != null && saleId > 0) {
                out.add("Ref: L-$saleLocalId")
            } else {
                out.add("SALE ID: L-$saleLocalId")
            }
        }
        if (out.isEmpty()) {
            out.add("SALE ID: —")
        }
        return out
    }

    fun hasAnyId(saleId: Int?, saleLocalId: Long?): Boolean =
        (saleId != null && saleId > 0) || (saleLocalId != null && saleLocalId > 0)
}

package com.pos.mobile.ui

import com.pos.mobile.data.local.entity.ProductEntity
import kotlin.math.roundToInt

/** Cart totals — same formulas as web renderCart / completeSale. */
object CartMath {

    fun lineTotal(line: CartLine): Double =
        line.product.sellingPrice * line.quantity - line.discount

    fun subtotal(lines: List<CartLine>): Double =
        lines.sumOf { it.product.sellingPrice * it.quantity }

    fun discountTotal(lines: List<CartLine>): Double =
        lines.sumOf { it.discount }

    fun grandTotal(lines: List<CartLine>): Double =
        subtotal(lines) - discountTotal(lines)

    fun normalizedQty(qty: Int): Int = maxOf(1, qty)

    fun normalizedDiscount(disc: Double): Double = maxOf(0.0, disc.roundToInt().toDouble())

    fun availableStock(product: ProductEntity): Double = WebPosRules.availableStock(product)

    /** @deprecated use [WebPosRules.checkoutStockIssues] */
    fun stockIssues(
        lines: List<CartLine>,
        productsById: Map<Int, ProductEntity>,
    ): String? = WebPosRules.checkoutStockIssues(lines, productsById)
}

data class CartTotals(
    val subtotal: Double,
    val discountTotal: Double,
    val total: Double,
)

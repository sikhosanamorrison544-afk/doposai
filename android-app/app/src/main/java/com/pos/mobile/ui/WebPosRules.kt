package com.pos.mobile.ui

import com.pos.mobile.data.local.entity.ProductEntity

/**
 * Business rules ported from web [static/js/app.js] (cart, stock, payments).
 */
object WebPosRules {

    fun availableStock(product: ProductEntity): Double =
        product.stockQty - product.reservedQty

    /** Warning when adding to cart (web addToCart) — does not block add. */
    fun addToCartWarning(product: ProductEntity, newTotalQty: Int): String? {
        val available = availableStock(product)
        return when {
            available <= 0 ->
                "Warning: ${product.name} is out of stock. Transaction will be blocked."
            newTotalQty > available ->
                "Warning: Adding would make total $newTotalQty, but only ${available.toInt()} available for ${product.name}."
            else -> null
        }
    }

    /** Qty edit warning (web renderCart qty change) — does not change typed qty. */
    fun qtyEditWarning(product: ProductEntity, requestedQty: Int): String? {
        val available = availableStock(product)
        return when {
            available <= 0 ->
                "Warning: ${product.name} is out of stock. Transaction will be blocked."
            requestedQty > available ->
                "Warning: Requested $requestedQty of ${product.name}, but only ${available.toInt()} available."
            else -> null
        }
    }

    /** Blocks checkout (web completeSale stock pre-check). */
    fun checkoutStockIssues(
        lines: List<CartLine>,
        productsById: Map<Int, ProductEntity>,
    ): String? {
        val issues = mutableListOf<String>()
        for (line in lines) {
            val product = productsById[line.product.id] ?: line.product
            val requested = CartMath.normalizedQty(line.quantity)
            val available = availableStock(product)
            val reserved = product.reservedQty
            val totalStock = product.stockQty
            when {
                available <= 0 ->
                    issues += "${line.product.name} - Out of stock (Available: 0, Reserved: $reserved, Total: $totalStock, Requested: $requested)"
                available < requested ->
                    issues += "${line.product.name} - Insufficient stock (Available: $available, Reserved: $reserved, Total: $totalStock, Requested: $requested)"
            }
        }
        return issues.takeIf { it.isNotEmpty() }?.joinToString("; ")
    }

    fun validatePayments(totalPay: Double, saleTotal: Double): String? = when {
        totalPay <= 0 -> "Enter at least one payment amount"
        totalPay + 0.01 < saleTotal ->
            "Insufficient payment: need ${"%.2f".format(saleTotal)}, got ${"%.2f".format(totalPay)}"
        else -> null
    }

    fun isOutOfStockForSearch(product: ProductEntity): Boolean =
        product.stockQty <= 0

    fun canSelectProductInSearch(product: ProductEntity): Boolean =
        availableStock(product) > 0

    fun roleCanAccessAdmin(role: String): Boolean = role == "admin"

    fun roleCanAccessPendingCollection(role: String): Boolean =
        role == "admin" || role == "supervisor"

    fun roleCanAccessWithdrawal(role: String): Boolean =
        role == "admin" || role == "supervisor"
}

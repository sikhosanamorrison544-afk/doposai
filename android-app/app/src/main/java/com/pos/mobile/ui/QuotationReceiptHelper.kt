package com.pos.mobile.ui

import android.content.Context
import androidx.appcompat.app.AppCompatActivity
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.ProductEntity
import com.pos.mobile.data.remote.PaymentInputDto
import com.pos.mobile.data.remote.QuotationReceiptDto
import com.pos.mobile.data.remote.QuotationReceiptItemDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

object QuotationReceiptHelper {

    fun cartLinesFromReceipt(
        items: List<QuotationReceiptItemDto>,
        productsById: Map<Int, ProductEntity>,
    ): List<CartLine> = items.map { item ->
        val product = productsById[item.product_id] ?: ProductEntity(
            id = item.product_id,
            name = item.product_name,
            barcode = null,
            categoryId = null,
            stockQty = 0.0,
            reservedQty = 0.0,
            sellingPrice = item.unit_price,
            costPrice = item.unit_price,
            isActive = true,
            serverSyncedAt = 0L,
        )
        CartLine(
            product = product.copy(sellingPrice = item.unit_price),
            quantity = item.quantity,
            discount = item.discount,
        )
    }

    fun buildSaleReceiptRequest(
        context: Context,
        receipt: QuotationReceiptDto,
        cartLines: List<CartLine>,
    ): ReceiptPrinter.SaleReceiptRequest {
        val prefs = context.getSharedPreferences("pos", Context.MODE_PRIVATE)
        val payments = receipt.payments.map { it.method to it.amount }
        return ReceiptPrinter.SaleReceiptRequest(
            storeName = prefs.getString("store_name", "Store") ?: "Store",
            cartLines = cartLines,
            subtotal = receipt.subtotal,
            discountTotal = receipt.discount_total,
            total = receipt.total,
            payments = payments,
            customerName = receipt.customer_name,
            collectionStatus = receipt.collection_status,
            cashierName = prefs.getString("username", null),
            saleId = receipt.sale_id,
            storePhone = prefs.getString("store_phone", "") ?: "",
            storeLocation = prefs.getString("store_location", "") ?: "",
        )
    }

    suspend fun deductLocalStock(context: Context, items: List<QuotationReceiptItemDto>) =
        withContext(Dispatchers.IO) {
            val dao = AppDatabase.getInstance(context).productDao()
            for (item in items) {
                dao.deductStock(item.product_id, item.quantity.toDouble())
            }
        }

    suspend fun printReceipt(
        activity: AppCompatActivity,
        receipt: QuotationReceiptDto,
    ): Boolean = withContext(Dispatchers.IO) {
        val db = AppDatabase.getInstance(activity)
        val products = db.productDao().getAllActiveList().associateBy { it.id }
        val cartLines = cartLinesFromReceipt(receipt.items, products)
        val request = buildSaleReceiptRequest(activity, receipt, cartLines)
        withContext(Dispatchers.Main) {
            ReceiptPrinter.printSaleAwait(activity, request)
        }
    }

    fun paymentsFromAmounts(
        cash: Double,
        mobile: Double,
        card: Double,
        credit: Double,
    ): List<PaymentInputDto> = buildList {
        if (cash > 0) add(PaymentInputDto("cash", cash))
        if (mobile > 0) add(PaymentInputDto("mobile_money", mobile))
        if (card > 0) add(PaymentInputDto("card", card))
        if (credit > 0) add(PaymentInputDto("credit", credit))
    }
}

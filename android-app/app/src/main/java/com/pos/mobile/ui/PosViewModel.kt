package com.pos.mobile.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.PaymentEntity
import com.pos.mobile.data.local.entity.SaleEntity
import com.pos.mobile.data.local.entity.SaleItemEntity
import com.pos.mobile.data.local.entity.SyncQueueEntity
import com.pos.mobile.data.local.entity.ProductEntity
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Cart line for in-memory POS cart (matches web app behaviour).
 */
data class CartLine(
    val product: ProductEntity,
    var quantity: Int,
    var discount: Double
) {
    val lineTotal: Double get() = (product.sellingPrice * quantity) - discount
}

class PosViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getInstance(application)
    private val productDao = db.productDao()
    private val saleDao = db.saleDao()
    private val saleItemDao = db.saleItemDao()
    private val paymentDao = db.paymentDao()
    private val syncQueueDao = db.syncQueueDao()

    val products: StateFlow<List<ProductEntity>> = productDao.getAllActive()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    private val _cart = MutableStateFlow<List<CartLine>>(emptyList())
    val cart: StateFlow<List<CartLine>> = _cart.asStateFlow()

    private val _saleCompleteMessage = MutableStateFlow<String?>(null)
    val saleCompleteMessage: StateFlow<String?> = _saleCompleteMessage.asStateFlow()

    val subtotal: Double get() = _cart.value.sumOf { it.product.sellingPrice * it.quantity }
    val discountTotal: Double get() = _cart.value.sumOf { it.discount }
    val total: Double get() = subtotal - discountTotal

    fun addToCart(product: ProductEntity, qty: Int = 1) {
        val list = _cart.value.toMutableList()
        val existing = list.indexOfFirst { it.product.id == product.id }
        val addQty = maxOf(1, qty)
        if (existing >= 0) {
            list[existing].quantity += addQty
        } else {
            list.add(CartLine(product = product, quantity = addQty, discount = 0.0))
        }
        _cart.value = list
    }

    fun removeFromCart(index: Int) {
        val list = _cart.value.toMutableList()
        if (index in list.indices) {
            list.removeAt(index)
            _cart.value = list
        }
    }

    fun updateQty(index: Int, qty: Int) {
        val list = _cart.value.toMutableList()
        if (index in list.indices) {
            list[index].quantity = maxOf(1, qty)
            _cart.value = list
        }
    }

    fun updateDiscount(index: Int, disc: Double) {
        val list = _cart.value.toMutableList()
        if (index in list.indices) {
            list[index].discount = maxOf(0.0, disc)
            _cart.value = list
        }
    }

    fun clearSaleMessage() {
        _saleCompleteMessage.value = null
    }

    fun completeSale(
        customerName: String?,
        cash: Double,
        mobile: Double,
        card: Double,
        credit: Double,
        collectionStatus: String,
        notes: String? = null
    ) {
        val cartList = _cart.value
        if (cartList.isEmpty()) {
            _saleCompleteMessage.value = "Cart is empty"
            return
        }
        val totalPay = cash + mobile + card + credit
        if (totalPay <= 0) {
            _saleCompleteMessage.value = "Enter at least one payment"
            return
        }
        if (kotlin.math.abs(totalPay - total) > 0.01) {
            _saleCompleteMessage.value = "Payments must equal total"
            return
        }
        viewModelScope.launch {
            try {
                val now = System.currentTimeMillis()
                val subtotalVal = subtotal
                val discountVal = discountTotal
                val totalVal = total
                val sale = SaleEntity(
                    cashierId = 1,
                    customerId = null,
                    subtotal = subtotalVal,
                    discountTotal = discountVal,
                    total = totalVal,
                    notes = notes ?: customerName?.takeIf { it.isNotBlank() },
                    collectionStatus = collectionStatus,
                    createdAt = now
                )
                val saleLocalId = saleDao.insert(sale)
                val items = cartList.map { line ->
                    SaleItemEntity(
                        saleLocalId = saleLocalId,
                        productId = line.product.id,
                        quantity = line.quantity,
                        unitPrice = line.product.sellingPrice,
                        discount = line.discount,
                        lineTotal = line.lineTotal
                    )
                }
                saleItemDao.insertAll(items)
                val payments = mutableListOf<PaymentEntity>()
                if (cash > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "cash", amount = cash))
                if (mobile > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "mobile_money", amount = mobile))
                if (card > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "card", amount = card))
                if (credit > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "credit", amount = credit))
                paymentDao.insertAll(payments)
                syncQueueDao.insert(SyncQueueEntity(saleLocalId = saleLocalId, createdAt = now, status = SyncQueueEntity.STATUS_PENDING))
                _cart.value = emptyList()
                _saleCompleteMessage.value = "Sale saved. Will sync when online."
            } catch (e: Exception) {
                _saleCompleteMessage.value = "Error: ${e.message}"
            }
        }
    }

    fun findProductByBarcode(barcode: String): ProductEntity? {
        val code = barcode.trim().uppercase()
        return products.value.find { it.barcode?.uppercase() == code }
    }

    fun searchProducts(query: String): List<ProductEntity> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return emptyList()
        return products.value.filter { it.name.lowercase().contains(q) }
    }
}

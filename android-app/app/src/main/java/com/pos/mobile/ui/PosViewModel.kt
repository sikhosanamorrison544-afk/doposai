package com.pos.mobile.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pos.mobile.BuildConfig
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.PaymentEntity
import com.pos.mobile.data.local.entity.SaleEntity
import com.pos.mobile.data.local.entity.SaleItemEntity
import com.pos.mobile.data.local.entity.SyncQueueEntity
import com.pos.mobile.data.local.entity.ProductEntity
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.data.remote.CustomerCreateDto
import com.pos.mobile.data.sync.SyncWorker
import com.pos.mobile.sync.NetworkUtils
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class CartLine(
    val product: ProductEntity,
    val quantity: Int,
    val discount: Double,
) {
    val lineTotal: Double get() = CartMath.lineTotal(this)
}

class PosViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getInstance(application)
    private val productDao = db.productDao()
    private val saleDao = db.saleDao()
    private val saleItemDao = db.saleItemDao()
    private val paymentDao = db.paymentDao()
    private val syncQueueDao = db.syncQueueDao()

    val products: StateFlow<List<ProductEntity>> = productDao.getAllActive()
        .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    private val _cart = MutableStateFlow<List<CartLine>>(emptyList())
    val cart: StateFlow<List<CartLine>> = _cart.asStateFlow()

    private val _posMessage = MutableStateFlow<String?>(null)
    val posMessage: StateFlow<String?> = _posMessage.asStateFlow()

    val cartTotals: StateFlow<CartTotals> = _cart.map { lines ->
        CartTotals(
            subtotal = CartMath.subtotal(lines),
            discountTotal = CartMath.discountTotal(lines),
            total = CartMath.grandTotal(lines),
        )
    }.stateIn(viewModelScope, SharingStarted.Eagerly, CartTotals(0.0, 0.0, 0.0))

    private val _saleEvents = MutableSharedFlow<SaleUiEvent>(extraBufferCapacity = 4)
    val saleEvents: SharedFlow<SaleUiEvent> = _saleEvents.asSharedFlow()

    private val _isCompletingSale = MutableStateFlow(false)
    val isCompletingSale: StateFlow<Boolean> = _isCompletingSale.asStateFlow()

    val subtotal: Double get() = CartMath.subtotal(_cart.value)
    val discountTotal: Double get() = CartMath.discountTotal(_cart.value)
    val total: Double get() = CartMath.grandTotal(_cart.value)

    fun clearPosMessage() {
        _posMessage.value = null
    }

    fun addToCart(product: ProductEntity, qty: Int = 1) {
        val addQty = CartMath.normalizedQty(qty)
        val list = _cart.value.toMutableList()
        val existing = list.indexOfFirst { it.product.id == product.id }
        val newTotalQty = if (existing >= 0) {
            list[existing].quantity + addQty
        } else {
            addQty
        }
        WebPosRules.addToCartWarning(product, newTotalQty)?.let { warn ->
            _posMessage.value = warn
        }
        if (existing >= 0) {
            list[existing] = list[existing].copy(quantity = newTotalQty)
        } else {
            list.add(CartLine(product = product, quantity = addQty, discount = 0.0))
        }
        _cart.value = list
    }

    fun onQtyUpdated(index: Int, qty: Int) {
        val list = _cart.value.toMutableList()
        if (index !in list.indices) return
        val line = list[index]
        val normalized = CartMath.normalizedQty(qty)
        WebPosRules.qtyEditWarning(line.product, normalized)?.let { warn ->
            _posMessage.value = warn
        } ?: run {
            if (_posMessage.value?.startsWith("Warning:") == true) {
                _posMessage.value = null
            }
        }
        list[index] = line.copy(quantity = normalized)
        _cart.value = list
    }

    fun removeFromCart(index: Int) {
        val list = _cart.value.toMutableList()
        if (index in list.indices) {
            list.removeAt(index)
            _cart.value = list
        }
    }

    fun updateQty(index: Int, qty: Int) = onQtyUpdated(index, qty)

    fun updateDiscount(index: Int, disc: Double) {
        val list = _cart.value.toMutableList()
        if (index in list.indices) {
            list[index] = list[index].copy(discount = CartMath.normalizedDiscount(disc))
            _cart.value = list
        }
    }

    fun completeSale(
        authToken: String?,
        cashierId: Int,
        customerName: String?,
        cash: Double,
        mobile: Double,
        card: Double,
        credit: Double,
        collectionStatus: String,
        notes: String? = null,
        receipt: ReceiptPrinter.SaleReceiptRequest? = null,
    ) {
        if (_isCompletingSale.value) return

        val cartList = _cart.value
        if (cartList.isEmpty()) {
            emitFailed("Cart is empty")
            return
        }

        val saleTotal = CartMath.grandTotal(cartList)
        var cashAmt = cash
        var mobileAmt = mobile
        var cardAmt = card
        var creditAmt = credit
        var totalPay = cashAmt + mobileAmt + cardAmt + creditAmt

        if (totalPay <= 0.005 && saleTotal > 0) {
            cashAmt = saleTotal
            totalPay = saleTotal
        }

        WebPosRules.validatePayments(totalPay, saleTotal)?.let {
            emitFailed(it)
            return
        }

        val online = NetworkUtils.isOnline(getApplication())

        _isCompletingSale.value = true
        viewModelScope.launch {
            try {
                val synced = withContext(Dispatchers.IO) {
                    if (online && !authToken.isNullOrBlank()) {
                        refreshProductsFromServer(authToken)
                    }
                    val productsById = productDao.getAllActiveList().associateBy { it.id }
                    if (online) {
                        WebPosRules.checkoutStockIssues(cartList, productsById)?.let { stockErr ->
                            throw IllegalStateException(
                                "Transaction blocked: $stockErr. Receipt will NOT be printed.",
                            )
                        }
                    }
                    val customerId = resolveCustomerId(authToken, customerName?.trim())
                    val now = System.currentTimeMillis()
                    val sale = SaleEntity(
                        cashierId = cashierId,
                        customerId = customerId,
                        subtotal = CartMath.subtotal(cartList),
                        discountTotal = CartMath.discountTotal(cartList),
                        total = saleTotal,
                        notes = notes ?: customerName?.takeIf { it.isNotBlank() && customerId == null },
                        collectionStatus = collectionStatus,
                        createdAt = now,
                    )
                    val saleLocalId = saleDao.insert(sale)
                    val items = cartList.map { line ->
                        SaleItemEntity(
                            saleLocalId = saleLocalId,
                            productId = line.product.id,
                            quantity = line.quantity,
                            unitPrice = line.product.sellingPrice,
                            discount = line.discount,
                            lineTotal = line.lineTotal,
                        )
                    }
                    saleItemDao.insertAll(items)
                    val payments = mutableListOf<PaymentEntity>()
                    if (cashAmt > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "cash", amount = cashAmt))
                    if (mobileAmt > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "mobile_money", amount = mobileAmt))
                    if (cardAmt > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "card", amount = cardAmt))
                    if (creditAmt > 0) payments.add(PaymentEntity(saleLocalId = saleLocalId, method = "credit", amount = creditAmt))
                    paymentDao.insertAll(payments)
                    syncQueueDao.insert(
                        SyncQueueEntity(
                            saleLocalId = saleLocalId,
                            createdAt = now,
                            status = SyncQueueEntity.STATUS_PENDING,
                        ),
                    )
                    for (line in cartList) {
                        productDao.deductStock(line.product.id, line.quantity.toDouble())
                    }

                    var syncedNow = false
                    if (online && !authToken.isNullOrBlank()) {
                        val prefs = getApplication<Application>().getSharedPreferences("pos", android.content.Context.MODE_PRIVATE)
                        val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
                            ?: BuildConfig.DEFAULT_API_BASE_URL
                        val api = SyncWorker.createApi(baseUrl)
                        val repo = SyncWorker.createRepository(getApplication(), baseUrl, api, db)
                        syncedNow = repo.pushPendingSales(authToken) > 0
                    }
                    syncedNow
                }
                _cart.value = emptyList()
                _posMessage.value = null
                _saleEvents.emit(
                    SaleUiEvent.Success(
                        message = getApplication<Application>().getString(
                            if (synced) com.pos.mobile.R.string.sale_synced_online
                            else com.pos.mobile.R.string.sale_saved_offline,
                        ),
                        receipt = receipt,
                    ),
                )
            } catch (e: Exception) {
                val msg = e.message ?: "unknown"
                _posMessage.value = msg
                emitFailed(msg)
            } finally {
                _isCompletingSale.value = false
            }
        }
    }

    private suspend fun refreshProductsFromServer(token: String) {
        val prefs = getApplication<Application>().getSharedPreferences("pos", android.content.Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL
        val api = SyncWorker.createApi(baseUrl)
        val repo = SyncWorker.createRepository(getApplication(), baseUrl, api, db)
        repo.pullProductsAndCustomers(token)
    }

    private suspend fun resolveCustomerId(token: String?, name: String?): Int? {
        if (name.isNullOrBlank()) return null
        if (token.isNullOrBlank() || !NetworkUtils.isOnline(getApplication())) return null
        return try {
            val api = createApi()
            val res = api.createCustomer("Bearer $token", CustomerCreateDto(name = name))
            if (res.isSuccessful) res.body()?.id else null
        } catch (_: Exception) {
            null
        }
    }

    private fun createApi(): ApiService {
        val prefs = getApplication<Application>().getSharedPreferences("pos", android.content.Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL
        return SyncWorker.createApi(baseUrl)
    }

    private fun emitFailed(message: String) {
        viewModelScope.launch {
            _saleEvents.emit(SaleUiEvent.Failed(message))
        }
    }

    suspend fun findProductByBarcode(barcode: String): ProductEntity? = withContext(Dispatchers.IO) {
        val code = barcode.trim()
        if (code.isEmpty()) return@withContext null
        productDao.findByBarcode(code) ?: productDao.findByBarcodeAny(code)
    }

    suspend fun searchProducts(query: String): List<ProductEntity> = withContext(Dispatchers.IO) {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return@withContext emptyList()
        val pattern = "%$q%"
        val fromDb = productDao.searchActive(pattern)
        if (fromDb.isNotEmpty()) return@withContext fromDb
        val any = productDao.searchAny(pattern)
        if (any.isNotEmpty()) return@withContext any
        products.value.filter {
            it.isActive &&
                (it.name.lowercase().contains(q) ||
                    (it.barcode?.lowercase()?.contains(q) == true))
        }.take(30)
    }
}

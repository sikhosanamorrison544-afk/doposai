package com.pos.mobile.data.sync

import android.content.Context
import android.util.Log
import org.json.JSONObject
import com.pos.mobile.data.local.dao.*
import com.pos.mobile.data.local.entity.*
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.data.remote.SaleCreateDto
import com.pos.mobile.data.remote.SaleItemInputDto
import com.pos.mobile.data.remote.PaymentInputDto
import com.pos.mobile.sync.MasterSyncEndpoints
import com.pos.mobile.sync.MasterSyncResult
import com.pos.mobile.sync.OfflineCacheKeys
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray

/**
 * Single source of truth: UI always reads from local DB.
 * This repository handles:
 * - Pull: fetch products/customers from API and write to local DB, update last_synced_at.
 * - Push: read unsynced sales from sync_queue, POST to API, mark synced and update last_synced_at.
 */
class SyncRepository(
    private val api: ApiService,
    private val productDao: ProductDao,
    private val categoryDao: CategoryDao,
    private val customerDao: CustomerDao,
    private val saleDao: SaleDao,
    private val saleItemDao: SaleItemDao,
    private val paymentDao: PaymentDao,
    private val syncQueueDao: SyncQueueDao,
    private val syncMetadataDao: SyncMetadataDao,
    private val apiCacheDao: ApiCacheDao,
    private val offlineMutationDao: OfflineMutationDao,
    private val supplierDao: SupplierDao,
    private val branchDao: BranchDao,
    private val enterpriseCacheDao: EnterpriseCacheDao,
    private val baseUrl: String,
) {
    companion object {
        private const val TAG = "SyncRepository"
    }

    suspend fun pullProductsAndCustomers(token: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val now = System.currentTimeMillis()
            val productsRes = api.getProducts("Bearer $token")
            if (!productsRes.isSuccessful) {
                val err = productsRes.errorBody()?.string() ?: "HTTP ${productsRes.code()}"
                syncMetadataDao.insert(
                    SyncMetadataEntity(
                        key = SyncMetadataEntity.KEY_PRODUCTS,
                        lastSyncedAt = now,
                        lastSyncSuccess = false
                    )
                )
                return@withContext Result.failure(Exception(err))
            }
            val list = productsRes.body() ?: emptyList()
            val entities = list.map { p ->
                ProductEntity(
                    id = p.id,
                    name = p.name,
                    barcode = p.barcode,
                    categoryId = p.category_id,
                    stockQty = p.stock_qty,
                    reservedQty = p.reserved_qty,
                    sellingPrice = p.selling_price,
                    costPrice = p.cost_price,
                    isActive = p.is_active,
                    serverSyncedAt = now,
                )
            }
            productDao.deleteAll()
            if (entities.isNotEmpty()) {
                productDao.insertAll(entities)
            }
            syncMetadataDao.insert(
                SyncMetadataEntity(
                    key = SyncMetadataEntity.KEY_PRODUCTS,
                    lastSyncedAt = now,
                    lastSyncSuccess = true
                )
            )

            val customersRes = api.getCustomers("Bearer $token")
            if (customersRes.isSuccessful) {
                val customers = customersRes.body() ?: emptyList()
                customerDao.deleteAll()
                if (customers.isNotEmpty()) {
                    val customerEntities = customers.map { c ->
                        CustomerEntity(
                            id = c.id,
                            name = c.name,
                            phone = c.phone,
                            email = c.email,
                            serverSyncedAt = now
                        )
                    }
                    customerDao.insertAll(customerEntities)
                }
                syncMetadataDao.insert(
                    SyncMetadataEntity(
                        key = SyncMetadataEntity.KEY_CUSTOMERS,
                        lastSyncedAt = now,
                        lastSyncSuccess = true
                    )
                )
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Cache store name, address, and phone for receipt printing. */
    suspend fun persistStoreSettings(context: Context, token: String) = withContext(Dispatchers.IO) {
        try {
            val url = baseUrl.trimEnd('/') + "/api/store-settings"
            val res = api.getUrl(url, "Bearer $token")
            if (!res.isSuccessful) return@withContext
            val body = res.body()?.string() ?: return@withContext
            val o = JSONObject(body)
            context.getSharedPreferences("pos", Context.MODE_PRIVATE).edit()
                .putString("store_name", o.optString("store_name", "All In One POS"))
                .putString("store_phone", o.optString("store_phone", ""))
                .putString("store_location", o.optString("store_location", ""))
                .apply()
        } catch (e: Exception) {
            Log.w(TAG, "persistStoreSettings failed", e)
        }
    }

    /**
     * Push one unsynced sale to the API. Called by SyncWorker for each pending row in sync_queue.
     */
    suspend fun pushSale(token: String, queueItem: SyncQueueEntity): Result<Int> = withContext(Dispatchers.IO) {
        try {
            val sale = saleDao.getByLocalId(queueItem.saleLocalId) ?: run {
                syncQueueDao.updateStatus(queueItem.id, SyncQueueEntity.STATUS_FAILED, "Sale not found")
                return@withContext Result.failure(Exception("Sale not found"))
            }
            val items = saleItemDao.getBySaleLocalId(queueItem.saleLocalId)
            val payments = paymentDao.getBySaleLocalId(queueItem.saleLocalId)
            val dto = SaleCreateDto(
                customer_id = sale.customerId,
                items = items.map { SaleItemInputDto(it.productId, it.quantity, it.unitPrice, it.discount) },
                payments = payments.map { PaymentInputDto(it.method, it.amount) },
                notes = sale.notes,
                collection_status = sale.collectionStatus
            )
            val response = api.createSale("Bearer $token", dto)
            if (!response.isSuccessful) {
                val err = response.errorBody()?.string() ?: "HTTP ${response.code()}"
                syncQueueDao.incrementRetry(queueItem.id, err)
                return@withContext Result.failure(Exception(err))
            }
            val serverId = response.body()!!.id
            val now = System.currentTimeMillis()
            saleDao.markSynced(queueItem.saleLocalId, serverId, now)
            syncQueueDao.updateStatus(queueItem.id, SyncQueueEntity.STATUS_SYNCED, null)
            syncMetadataDao.insert(
                SyncMetadataEntity(
                    key = SyncMetadataEntity.KEY_SALES_PUSH,
                    lastSyncedAt = now,
                    lastSyncSuccess = true
                )
            )
            Result.success(serverId)
        } catch (e: Exception) {
            syncQueueDao.incrementRetry(queueItem.id, e.message)
            Result.failure(e)
        }
    }

    suspend fun getPendingSyncCount(): Int = withContext(Dispatchers.IO) {
        syncQueueDao.getByStatus(SyncQueueEntity.STATUS_PENDING).size
    }

    suspend fun getLastSyncedAt(key: String): Long? = withContext(Dispatchers.IO) {
        syncMetadataDao.get(key)?.lastSyncedAt
    }

    /**
     * Full pull from Render master DB: Room product/customer tables + JSON cache for WebView pages.
     */
    suspend fun pullEnterpriseData(token: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val bearer = "Bearer $token"
            val base = baseUrl.trimEnd('/')
            val now = System.currentTimeMillis()
            val bundleRes = api.getUrl("$base/api/enterprise/offline-bundle", bearer)
            if (bundleRes.isSuccessful) {
                val body = bundleRes.body()?.string() ?: "{}"
                enterpriseCacheDao.put(
                    EnterpriseCacheEntity("offline_bundle", body, now)
                )
                val root = org.json.JSONObject(body)
                val suppliers = root.optJSONArray("suppliers")
                if (suppliers != null) {
                    val entities = mutableListOf<SupplierEntity>()
                    for (i in 0 until suppliers.length()) {
                        val o = suppliers.getJSONObject(i)
                        entities.add(
                            SupplierEntity(
                                id = o.getInt("id"),
                                businessName = o.getString("business_name"),
                                phone = o.optString("phone", null).takeIf { it.isNotEmpty() },
                                whatsappNumber = o.optString("whatsapp_number", null).takeIf { it.isNotEmpty() },
                                balance = o.optDouble("balance", 0.0),
                                serverSyncedAt = now,
                            )
                        )
                    }
                    supplierDao.deleteAll()
                    if (entities.isNotEmpty()) supplierDao.insertAll(entities)
                }
                val branches = root.optJSONArray("branches")
                if (branches != null) {
                    val entities = mutableListOf<BranchEntity>()
                    for (i in 0 until branches.length()) {
                        val o = branches.getJSONObject(i)
                        entities.add(
                            BranchEntity(
                                id = o.getInt("id"),
                                name = o.getString("name"),
                                code = o.optString("code", null).takeIf { it.isNotEmpty() },
                                isDefault = o.optBoolean("is_default", false),
                                serverSyncedAt = now,
                            )
                        )
                    }
                    branchDao.deleteAll()
                    if (entities.isNotEmpty()) branchDao.insertAll(entities)
                }
                val pos = root.optJSONArray("purchase_orders")
                if (pos != null) {
                    enterpriseCacheDao.put(
                        EnterpriseCacheEntity("open_purchase_orders", pos.toString(), now)
                    )
                }
            }
            val suppliersRes = api.getUrl("$base/api/enterprise/suppliers", bearer)
            if (suppliersRes.isSuccessful) {
                enterpriseCacheDao.put(
                    EnterpriseCacheEntity(
                        "suppliers_list",
                        suppliersRes.body()?.string() ?: "[]",
                        now,
                    )
                )
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.w(TAG, "pullEnterpriseData partial failure", e)
            Result.failure(e)
        }
    }

    suspend fun syncMasterDatabase(context: Context, token: String): Result<MasterSyncResult> = withContext(Dispatchers.IO) {
        try {
            pullProductsAndCustomers(token).getOrElse { return@withContext Result.failure(it) }
            persistStoreSettings(context, token)
            pullEnterpriseData(token)
            pushOfflineMutations(token)

            val bearer = "Bearer $token"
            val base = baseUrl.trimEnd('/')
            val now = System.currentTimeMillis()
            val cacheEntries = mutableListOf<ApiCacheEntity>()
            var apiOk = 0
            var apiFail = 0

            for (fullPath in MasterSyncEndpoints.apiPathsForSync()) {
                val pathOnly = fullPath.substringBefore('?')
                val query = fullPath.substringAfter('?', "").takeIf { it.isNotEmpty() }
                val cacheKey = OfflineCacheKeys.forGet(pathOnly, query)
                val url = base + fullPath
                val res = api.getUrl(url, bearer)
                if (res.isSuccessful) {
                    val body = res.body()?.string() ?: "[]"
                    val contentType = res.headers()["Content-Type"] ?: "application/json"
                    cacheEntries.add(
                        ApiCacheEntity(cacheKey, body, contentType, res.code(), now)
                    )
                    apiOk++
                } else {
                    apiFail++
                    Log.w(TAG, "Cache miss for $fullPath: HTTP ${res.code()}")
                }
            }

            var laybyPayments = 0
            val txKey = OfflineCacheKeys.forGet("/api/layby/transactions", null)
            cacheEntries.find { it.cacheKey == txKey }?.let { txCache ->
                try {
                    val arr = JSONArray(txCache.responseBody)
                    for (i in 0 until arr.length()) {
                        val id = arr.getJSONObject(i).optInt("id", -1)
                        if (id < 0) continue
                        val payPath = "/api/layby/payments/$id"
                        val payRes = api.getUrl(base + payPath, bearer)
                        if (payRes.isSuccessful) {
                            cacheEntries.add(
                                ApiCacheEntity(
                                    OfflineCacheKeys.forGet(payPath, null),
                                    payRes.body()?.string() ?: "[]",
                                    payRes.headers()["Content-Type"] ?: "application/json",
                                    payRes.code(),
                                    now,
                                )
                            )
                            laybyPayments++
                        }
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "Layby payment cache prefetch failed", e)
                }
            }

            var pagesOk = 0
            for (page in MasterSyncEndpoints.webPages) {
                val res = api.getUrl(base + page, bearer)
                if (res.isSuccessful) {
                    cacheEntries.add(
                        ApiCacheEntity(
                            OfflineCacheKeys.forGet(page, null),
                            res.body()?.string() ?: "",
                            res.headers()["Content-Type"] ?: "text/html",
                            res.code(),
                            now,
                        )
                    )
                    pagesOk++
                }
            }

            if (cacheEntries.isNotEmpty()) {
                apiCacheDao.deleteAll()
                apiCacheDao.putAll(cacheEntries)
            }

            syncMetadataDao.insert(
                SyncMetadataEntity(
                    key = SyncMetadataEntity.KEY_MASTER_CACHE,
                    lastSyncedAt = now,
                    lastSyncSuccess = apiFail == 0,
                )
            )

            Result.success(
                MasterSyncResult(
                    apiEndpointsCached = apiOk,
                    apiEndpointsFailed = apiFail,
                    webPagesCached = pagesOk,
                    laybyPaymentCaches = laybyPayments,
                )
            )
        } catch (e: Exception) {
            Log.e(TAG, "syncMasterDatabase failed", e)
            Result.failure(e)
        }
    }

    suspend fun pushOfflineMutations(token: String): Int = withContext(Dispatchers.IO) {
        val bearer = "Bearer $token"
        val base = baseUrl.trimEnd('/')
        var pushed = 0
        val pending = offlineMutationDao.getByStatus(OfflineMutationEntity.STATUS_PENDING)
        for (m in pending) {
            val url = base + m.path
            val mediaType = (m.contentType ?: "application/json").substringBefore(';').toMediaType()
            val body = (m.requestBody ?: "{}").toRequestBody(mediaType)
            val res = when (m.method.uppercase()) {
                "POST" -> api.postUrl(url, bearer, body)
                "PUT" -> api.putUrl(url, bearer, body)
                "PATCH" -> api.postUrl(url, bearer, body)
                "DELETE" -> api.deleteUrl(url, bearer)
                else -> continue
            }
            if (res.isSuccessful) {
                offlineMutationDao.updateStatus(m.id, OfflineMutationEntity.STATUS_SYNCED, null)
                pushed++
            } else {
                offlineMutationDao.updateStatus(
                    m.id,
                    OfflineMutationEntity.STATUS_FAILED,
                    res.errorBody()?.string() ?: "HTTP ${res.code()}",
                )
            }
        }
        pushed
    }
}

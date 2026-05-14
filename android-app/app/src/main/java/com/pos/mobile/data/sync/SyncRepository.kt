package com.pos.mobile.data.sync

import com.pos.mobile.data.local.dao.*
import com.pos.mobile.data.local.entity.*
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.data.remote.SaleCreateDto
import com.pos.mobile.data.remote.SaleItemInputDto
import com.pos.mobile.data.remote.PaymentInputDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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
    private val syncMetadataDao: SyncMetadataDao
) {

    suspend fun pullProductsAndCustomers(token: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val productsRes = api.getProducts("Bearer $token")
            if (productsRes.isSuccessful) {
                productsRes.body()?.let { list ->
                    val entities = list.map { p ->
                        ProductEntity(
                            id = p.id,
                            name = p.name,
                            barcode = p.barcode,
                            categoryId = p.category_id,
                            stockQty = p.stock_qty,
                            sellingPrice = p.selling_price,
                            costPrice = p.cost_price,
                            isActive = p.is_active,
                            serverSyncedAt = System.currentTimeMillis()
                        )
                    }
                    productDao.insertAll(entities)
                }
                syncMetadataDao.insert(
                    SyncMetadataEntity(
                        key = SyncMetadataEntity.KEY_PRODUCTS,
                        lastSyncedAt = System.currentTimeMillis(),
                        lastSyncSuccess = true
                    )
                )
            }
            val customersRes = api.getCustomers("Bearer $token")
            if (customersRes.isSuccessful) {
                customersRes.body()?.let { list ->
                    val entities = list.map { c ->
                        CustomerEntity(
                            id = c.id,
                            name = c.name,
                            phone = c.phone,
                            email = c.email,
                            serverSyncedAt = System.currentTimeMillis()
                        )
                    }
                    customerDao.insertAll(entities)
                }
                syncMetadataDao.insert(
                    SyncMetadataEntity(
                        key = SyncMetadataEntity.KEY_CUSTOMERS,
                        lastSyncedAt = System.currentTimeMillis(),
                        lastSyncSuccess = true
                    )
                )
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
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
}

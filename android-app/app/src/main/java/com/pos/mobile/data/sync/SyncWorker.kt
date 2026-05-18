package com.pos.mobile.data.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.SyncQueueEntity
import com.pos.mobile.data.remote.ApiService
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Background sync: when internet becomes available, push unsynced transactions to the cloud API.
 * Schedule with Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).
 * Run every 15–30 min or after network state change.
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val baseUrl = inputData.getString(KEY_BASE_URL)
            ?: applicationContext.getSharedPreferences("pos", Context.MODE_PRIVATE).getString("base_url", null)
            ?: return Result.failure()
        val token = inputData.getString(KEY_TOKEN)
            ?: applicationContext.getSharedPreferences("pos", Context.MODE_PRIVATE).getString("token", null)
            ?: return Result.failure()

        val db = AppDatabase.getInstance(applicationContext)
        val api = createApi(baseUrl)
        val repo = createRepository(applicationContext, baseUrl, api, db)

        return try {
            repo.syncMasterDatabase(token)

            val pending = db.syncQueueDao().getByStatus(SyncQueueEntity.STATUS_PENDING)
            var pushed = 0
            for (item in pending) {
                repo.pushSale(token, item).onSuccess { pushed++ }.onFailure {
                    Log.w(TAG, "Push failed for queue id ${item.id}: $it")
                }
            }
            Result.success(workDataOf(KEY_PUSHED to pushed))
        } catch (e: Exception) {
            Log.e(TAG, "Sync failed", e)
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "SyncWorker"
        const val KEY_BASE_URL = "base_url"
        const val KEY_TOKEN = "token"
        const val KEY_PUSHED = "pushed"

        fun createRepository(
            context: android.content.Context,
            baseUrl: String,
            api: ApiService,
            db: com.pos.mobile.data.local.AppDatabase,
        ): SyncRepository = SyncRepository(
            api = api,
            productDao = db.productDao(),
            categoryDao = db.categoryDao(),
            customerDao = db.customerDao(),
            saleDao = db.saleDao(),
            saleItemDao = db.saleItemDao(),
            paymentDao = db.paymentDao(),
            syncQueueDao = db.syncQueueDao(),
            syncMetadataDao = db.syncMetadataDao(),
            apiCacheDao = db.apiCacheDao(),
            offlineMutationDao = db.offlineMutationDao(),
            baseUrl = baseUrl,
        )

        fun createApi(baseUrl: String): ApiService {
            val client = OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .build()
            val url = if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
            return Retrofit.Builder()
                .baseUrl(url)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
                .create(ApiService::class.java)
        }
    }
}

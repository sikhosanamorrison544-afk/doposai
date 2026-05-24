package com.pos.mobile.data.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.local.AppDatabase
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
        val prefs = applicationContext.getSharedPreferences("pos", Context.MODE_PRIVATE)
        val token = inputData.getString(KEY_TOKEN)
            ?: SessionStore(applicationContext).getAccessToken()
            ?: prefs.getString("token", null)
            ?: return Result.failure()

        val db = AppDatabase.getInstance(applicationContext)
        val api = createApi(baseUrl)
        val repo = createRepository(applicationContext, baseUrl, api, db)
        val forceFull = inputData.getBoolean(KEY_FULL_CACHE, false)
        val fullCache = forceFull || shouldPrefetchApiCache(prefs)

        return try {
            var pushed = repo.pushPendingSales(token)
            val pendingMutations = repo.pushOfflineMutations(token)
            if (pendingMutations > 0) {
                Log.i(TAG, "Pushed $pendingMutations offline mutation(s)")
            }
            try {
                repo.syncMasterDatabase(applicationContext, token, fullCache = fullCache)
                if (fullCache) {
                    prefs.edit().putLong(KEY_LAST_FULL_CACHE_MS, System.currentTimeMillis()).apply()
                }
            } catch (e: Exception) {
                Log.w(TAG, "Catalog/cache sync failed after uploading $pushed sale(s)", e)
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
        /** When true, prefetch optional offline API cache (admin pages are never bulk-fetched). */
        const val KEY_FULL_CACHE = "full_cache"
        private const val KEY_LAST_FULL_CACHE_MS = "last_full_cache_sync_ms"
        private const val FULL_CACHE_INTERVAL_MS = 10L * 60 * 1000

        fun shouldPrefetchApiCache(prefs: android.content.SharedPreferences): Boolean {
            val last = prefs.getLong(KEY_LAST_FULL_CACHE_MS, 0L)
            return last == 0L || System.currentTimeMillis() - last >= FULL_CACHE_INTERVAL_MS
        }

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
            supplierDao = db.supplierDao(),
            branchDao = db.branchDao(),
            enterpriseCacheDao = db.enterpriseCacheDao(),
            baseUrl = baseUrl,
        )

        fun createApi(baseUrl: String, readTimeoutSec: Long = 25): ApiService {
            val client = OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(readTimeoutSec, TimeUnit.SECONDS)
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

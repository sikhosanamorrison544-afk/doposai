package com.pos.mobile.data.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.sync.NetworkUtils
import com.pos.mobile.sync.SaleSyncPipeline
import com.pos.mobile.sync.SyncPolicy
import com.pos.mobile.sync.SyncScheduler
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Background sync: push unsynced transactions to the cloud API, then refresh catalog
 * via [SaleSyncPipeline] (same order as the manual Sync button).
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val baseUrl = inputData.getString(KEY_BASE_URL)
            ?: applicationContext.getSharedPreferences("pos", Context.MODE_PRIVATE).getString("base_url", null)
            ?: return Result.retry()
        val prefs = applicationContext.getSharedPreferences("pos", Context.MODE_PRIVATE)
        val drainMode = inputData.getBoolean(KEY_DRAIN_MODE, false)
        val pushOnly = inputData.getBoolean(KEY_PUSH_ONLY, false) || drainMode
        val forceFull = inputData.getBoolean(KEY_FULL_CACHE, false)
        val fullCache = forceFull || (!pushOnly && shouldPrefetchApiCache(prefs))

        if (!NetworkUtils.hasValidatedInternet(applicationContext)) {
            Log.i(TAG, "Skip sync — network not validated yet")
            SyncScheduler.enqueueStickyDrain(applicationContext)
            return Result.retry()
        }

        val db = AppDatabase.getInstance(applicationContext)
        val api = createApi(baseUrl)
        val repo = createRepository(applicationContext, baseUrl, api, db)

        return try {
            // Same pipeline as the manual Sync button: auth → drain → catalog
            // (catalog only runs when the upload queue is empty).
            val pipeline = SaleSyncPipeline.run(
                context = applicationContext,
                repo = repo,
                refreshCatalog = true,
            )
            if (pipeline.offline || pipeline.authRequired) {
                SyncScheduler.enqueueStickyDrain(applicationContext)
                return Result.retry()
            }

            val salesPushed = pipeline.salesPushed
            val mutationsPushed = pipeline.mutationsPushed
            val salesRemaining = pipeline.salesRemaining.coerceAtLeast(0)
            val mutationsRemaining = pipeline.mutationsRemaining.coerceAtLeast(0)
            val oldestAgeMs = pipeline.oldestPendingAgeMs
            val token = pipeline.token

            if (mutationsPushed > 0) {
                Log.i(TAG, "Pushed $mutationsPushed offline mutation(s)")
            }
            if (oldestAgeMs >= SyncPolicy.SYNC_WARN_AGE_MS) {
                Log.w(
                    TAG,
                    "Pending sync aging: oldest=${oldestAgeMs / 3600000}h " +
                        "(warn_window=${SyncPolicy.SYNC_DEADLINE_MS / 3600000}h; pending retained)",
                )
            }

            // Optional heavy API cache only after uploads are clear.
            if (!pushOnly && salesRemaining == 0 && mutationsRemaining == 0 && token != null) {
                if (NetworkUtils.isGoodNetworkForHeavySync(applicationContext)) {
                    try {
                        repo.prefetchApiCache(token, fullCache).onSuccess {
                            if (fullCache) {
                                prefs.edit()
                                    .putLong(KEY_LAST_FULL_CACHE_MS, System.currentTimeMillis())
                                    .apply()
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "Optional cache prefetch failed (stock sync OK)", e)
                    }
                } else {
                    Log.i(TAG, "Heavy API cache deferred — Wi‑Fi/unmetered only")
                }
            }

            val remaining = salesRemaining + mutationsRemaining
            // Never report success while unsynchronized sales remain.
            if (remaining > 0 || pipeline.hadRetryableFailures) {
                val expedite = oldestAgeMs >= SyncPolicy.SYNC_WARN_AGE_MS
                SyncScheduler.enqueueStickyDrain(applicationContext, expedite = expedite)
                Log.i(
                    TAG,
                    "SALE_SYNC: result=QUEUE_REMAINING sales=$salesRemaining mut=$mutationsRemaining action=retry",
                )
                return Result.retry()
            }

            Result.success(
                workDataOf(
                    KEY_PUSHED to (salesPushed + mutationsPushed),
                    KEY_REMAINING to remaining,
                ),
            )
        } catch (e: Exception) {
            Log.e(TAG, "Sync failed", e)
            SyncScheduler.enqueueStickyDrain(applicationContext)
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "SyncWorker"
        const val KEY_BASE_URL = "base_url"
        const val KEY_TOKEN = "token"
        const val KEY_PUSHED = "pushed"
        const val KEY_REMAINING = "remaining"
        /** When true, prefetch optional offline API cache (admin pages are never bulk-fetched). */
        const val KEY_FULL_CACHE = "full_cache"
        /** When true, only upload pending sales/mutations — no catalog pull. */
        const val KEY_PUSH_ONLY = "push_only"
        /** Sticky drain mode — keep retrying until queue is empty. */
        const val KEY_DRAIN_MODE = "drain_mode"
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

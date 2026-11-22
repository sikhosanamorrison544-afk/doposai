package com.pos.mobile.sync

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.pos.mobile.BuildConfig
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.sync.SyncWorker
import java.util.concurrent.TimeUnit

/**
 * Coordinates background sync: upload pending sales and download product/stock
 * on any validated internet; defer optional heavy API cache until Wi‑Fi/unmetered.
 *
 * Sticky drain work stays scheduled until the queue is empty (re-enqueued by the
 * worker when items remain), targeting delivery within [SyncPolicy.SYNC_DEADLINE_MS].
 */
object SyncScheduler {

    private const val TAG = "SyncScheduler"
    const val WORK_PUSH = "pos_sync_push"
    const val WORK_FULL = "pos_sync_full"
    const val WORK_DRAIN = "pos_sync_drain_pending"
    const val WORK_PERIODIC = "pos_sync_work"
    private const val WORK_CATALOG = "pos_sync_catalog"

    /** Upload queued sales/mutations only — safe on mobile data once validated. */
    fun enqueuePushOnly(context: Context) {
        val (baseUrl, token) = credentials(context) ?: run {
            Log.d(TAG, "Skip push sync — missing credentials")
            return
        }
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_BASE_URL to baseUrl,
                    SyncWorker.KEY_TOKEN to token,
                    SyncWorker.KEY_PUSH_ONLY to true,
                    SyncWorker.KEY_FULL_CACHE to false,
                ),
            )
            .addTag(WORK_PUSH)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            WORK_PUSH,
            ExistingWorkPolicy.KEEP,
            work,
        )
    }

    /**
     * Always schedule a CONNECTED push drain (even if currently offline).
     * WorkManager runs it when the network returns — critical for ≤3 day delivery.
     *
     * @param replace when true (after a new sale), replace any backoff-delayed drain
     * so the new sale is not stuck behind a KEEP'd failed worker.
     */
    fun enqueueStickyDrain(context: Context, expedite: Boolean = false, replace: Boolean = false) {
        val (baseUrl, token) = credentials(context) ?: run {
            Log.d(TAG, "Skip sticky drain — missing credentials")
            return
        }
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val builder = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_BASE_URL to baseUrl,
                    SyncWorker.KEY_TOKEN to token,
                    SyncWorker.KEY_PUSH_ONLY to true,
                    SyncWorker.KEY_FULL_CACHE to false,
                    SyncWorker.KEY_DRAIN_MODE to true,
                ),
            )
            .addTag(WORK_DRAIN)
        if (expedite) {
            try {
                builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            } catch (_: Exception) {
                // Older devices / quota — still enqueued as normal work.
            }
        }
        val policy = if (replace || expedite) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP
        WorkManager.getInstance(context).enqueueUniqueWork(
            WORK_DRAIN,
            policy,
            builder.build(),
        )
        Log.i(TAG, "Sticky drain enqueued (expedite=$expedite replace=${replace || expedite})")
    }

    /** Full master DB sync — only when network quality is good. */
    fun enqueueFullSyncIfGoodNetwork(context: Context, fullCache: Boolean = false) {
        if (!NetworkUtils.isGoodNetworkForHeavySync(context)) {
            Log.d(TAG, "Defer heavy sync — waiting for Wi‑Fi or unmetered network")
            enqueueStickyDrain(context)
            return
        }
        val (baseUrl, token) = credentials(context) ?: return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_BASE_URL to baseUrl,
                    SyncWorker.KEY_TOKEN to token,
                    SyncWorker.KEY_PUSH_ONLY to false,
                    SyncWorker.KEY_FULL_CACHE to fullCache,
                ),
            )
            .addTag(WORK_FULL)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            WORK_FULL,
            ExistingWorkPolicy.KEEP,
            work,
        )
    }

    /**
     * Download products/stock (and customers) into local Room DB.
     * Runs on any validated internet (Wi‑Fi or mobile data).
     * SyncWorker itself refuses catalog pull while uploads remain open.
     */
    fun enqueueCatalogSync(context: Context) {
        if (!NetworkUtils.hasValidatedInternet(context)) {
            Log.d(TAG, "Skip catalog sync — no validated internet")
            enqueueStickyDrain(context)
            return
        }
        val (baseUrl, token) = credentials(context) ?: return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_BASE_URL to baseUrl,
                    SyncWorker.KEY_TOKEN to token,
                    SyncWorker.KEY_PUSH_ONLY to false,
                    SyncWorker.KEY_FULL_CACHE to false,
                ),
            )
            .addTag(WORK_CATALOG)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            WORK_CATALOG,
            ExistingWorkPolicy.KEEP,
            work,
        )
    }

    /**
     * After sale or reconnect: upload pending sales first.
     *
     * Do NOT enqueue a parallel catalog worker here — a racing catalog pull can
     * restore pre-sale stock while uploads are still in flight. SyncWorker's
     * push-only drain refreshes catalog after the queue is empty.
     */
    fun enqueueAfterSaleOrReconnect(context: Context) {
        enqueueStickyDrain(context, expedite = true, replace = true)
    }

    /** Periodic safety net (≤15 min when constraints allow). */
    fun schedulePeriodic(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_FULL_CACHE to false,
                    SyncWorker.KEY_DRAIN_MODE to true,
                ),
            )
            .addTag("pos_sync")
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_PERIODIC,
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
        enqueueStickyDrain(context)
    }

    private fun credentials(context: Context): Pair<String, String>? {
        val prefs = context.getSharedPreferences("pos", Context.MODE_PRIVATE)
        var baseUrl = prefs.getString("base_url", null)?.trim().orEmpty()
        if (baseUrl.isEmpty()) {
            baseUrl = BuildConfig.DEFAULT_API_BASE_URL.trim()
            if (baseUrl.isNotEmpty()) {
                prefs.edit().putString("base_url", baseUrl).apply()
            }
        }
        if (baseUrl.isEmpty()) return null
        val token = SessionStore(context).getAccessToken()
            ?: prefs.getString("token", null)
        if (token.isNullOrBlank()) return null
        return baseUrl to token
    }
}

package com.pos.mobile.sync

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.sync.SyncWorker

/**
 * Coordinates background sync: upload pending sales and download product/stock
 * on any validated internet; defer optional heavy API cache until Wi‑Fi/unmetered.
 */
object SyncScheduler {

    private const val TAG = "SyncScheduler"
    private const val WORK_PUSH = "pos_sync_push"
    private const val WORK_FULL = "pos_sync_full"

    /** Upload queued sales/mutations only — safe on mobile data once validated. */
    fun enqueuePushOnly(context: Context) {
        if (!NetworkUtils.canSyncPendingSales(context)) {
            Log.d(TAG, "Skip push sync — no validated internet")
            return
        }
        val (baseUrl, token) = credentials(context) ?: return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
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
            ExistingWorkPolicy.REPLACE,
            work,
        )
    }

    /** Full master DB sync — only when network quality is good. */
    fun enqueueFullSyncIfGoodNetwork(context: Context, fullCache: Boolean = false) {
        if (!NetworkUtils.isGoodNetworkForHeavySync(context)) {
            Log.d(TAG, "Defer heavy sync — waiting for Wi‑Fi or unmetered network")
            enqueuePushOnly(context)
            return
        }
        val (baseUrl, token) = credentials(context) ?: return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
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
            ExistingWorkPolicy.REPLACE,
            work,
        )
    }

    /**
     * Download products/stock (and customers) into local Room DB.
     * Runs on any validated internet (Wi‑Fi or mobile data).
     */
    fun enqueueCatalogSync(context: Context) {
        if (!NetworkUtils.hasValidatedInternet(context)) {
            Log.d(TAG, "Skip catalog sync — no validated internet")
            return
        }
        val (baseUrl, token) = credentials(context) ?: return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_BASE_URL to baseUrl,
                    SyncWorker.KEY_TOKEN to token,
                    SyncWorker.KEY_PUSH_ONLY to false,
                    SyncWorker.KEY_FULL_CACHE to false,
                ),
            )
            .addTag("pos_sync_catalog")
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "pos_sync_catalog",
            ExistingWorkPolicy.REPLACE,
            work,
        )
    }

    /** After sale or reconnect: upload pending sales, then refresh local stock from server. */
    fun enqueueAfterSaleOrReconnect(context: Context) {
        enqueuePushOnly(context)
        enqueueCatalogSync(context)
        if (NetworkUtils.isGoodNetworkForHeavySync(context)) {
            enqueueFullSyncIfGoodNetwork(context, fullCache = false)
        }
    }

    private fun credentials(context: Context): Pair<String, String>? {
        val prefs = context.getSharedPreferences("pos", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("base_url", null)?.trim().orEmpty()
        if (baseUrl.isEmpty()) return null
        val token = SessionStore(context).getAccessToken()
            ?: prefs.getString("token", null)
        if (token.isNullOrBlank()) return null
        return baseUrl to token
    }
}

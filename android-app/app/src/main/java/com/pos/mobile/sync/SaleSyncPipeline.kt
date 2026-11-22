package com.pos.mobile.sync

import android.content.Context
import android.util.Log
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.local.entity.SyncQueueEntity
import com.pos.mobile.data.sync.SyncRepository
import com.pos.mobile.ui.BearerResult
import com.pos.mobile.ui.PosAuth

/**
 * Single upload→catalog pipeline for automatic WorkManager sync and the manual Sync button.
 *
 * Order is fixed:
 * 1) ensure auth (refresh if needed)
 * 2) requeue orphans + drain pending sales/mutations
 * 3) only then refresh catalog / reconcile local stock
 */
object SaleSyncPipeline {
    private const val TAG = "SaleSyncPipeline"

    data class Result(
        val salesPushed: Int,
        val mutationsPushed: Int,
        val salesRemaining: Int,
        val mutationsRemaining: Int,
        val oldestPendingAgeMs: Long,
        val catalogRefreshed: Boolean,
        val offline: Boolean,
        val authRequired: Boolean,
        val token: String? = null,
    ) {
        /** -1 remaining means drain was skipped (offline/auth); treat as unknown/open. */
        val openUploads: Int
            get() = if (salesRemaining < 0 || mutationsRemaining < 0) {
                Int.MAX_VALUE
            } else {
                salesRemaining + mutationsRemaining
            }
        val hadRetryableFailures: Boolean get() = openUploads > 0
    }

    /**
     * @param refreshCatalog when true and the upload queue is empty, pull products/stock.
     */
    suspend fun run(
        context: Context,
        repo: SyncRepository,
        refreshCatalog: Boolean,
    ): Result {
        if (!NetworkUtils.hasValidatedInternet(context) && !NetworkUtils.isOnline(context)) {
            SaleSyncLog.event(
                clientSaleId = null,
                result = "NETWORK_UNAVAILABLE",
                action = "wait_for_internet",
            )
            return Result(
                salesPushed = 0,
                mutationsPushed = 0,
                salesRemaining = -1,
                mutationsRemaining = -1,
                oldestPendingAgeMs = 0L,
                catalogRefreshed = false,
                offline = true,
                authRequired = false,
            )
        }

        val bearer = when (val b = PosAuth.ensureBearer(context)) {
            is BearerResult.Ok -> b.bearer.removePrefix("Bearer ").trim()
            BearerResult.Offline -> {
                SaleSyncLog.event(
                    clientSaleId = null,
                    result = "NETWORK_UNAVAILABLE",
                    action = "wait_for_internet",
                )
                return Result(
                    salesPushed = 0,
                    mutationsPushed = 0,
                    salesRemaining = -1,
                    mutationsRemaining = -1,
                    oldestPendingAgeMs = 0L,
                    catalogRefreshed = false,
                    offline = true,
                    authRequired = false,
                )
            }
            BearerResult.Missing, BearerResult.Expired -> {
                SaleSyncLog.event(
                    clientSaleId = null,
                    result = "AUTH_${b.javaClass.simpleName.uppercase()}",
                    action = "retry_auth",
                )
                // Never POST with a dead JWT; keep every queued sale.
                return Result(
                    salesPushed = 0,
                    mutationsPushed = 0,
                    salesRemaining = -1,
                    mutationsRemaining = -1,
                    oldestPendingAgeMs = 0L,
                    catalogRefreshed = false,
                    offline = false,
                    authRequired = true,
                )
            }
        }

        val salesDrain = repo.drainPendingSales(bearer)
        val mutDrain = repo.drainOfflineMutations(bearer)
        val remaining = salesDrain.remaining + mutDrain.remaining
        var catalogOk = false
        if (refreshCatalog && remaining == 0) {
            try {
                val essentials = repo.syncEssentials(context, bearer)
                catalogOk = essentials.isSuccess
                if (catalogOk) {
                    SessionStore(context).recordOfflineAnchor()
                    Log.i(TAG, "Catalog reconciled after empty upload queue")
                } else {
                    Log.w(TAG, "Catalog refresh failed: ${essentials.exceptionOrNull()?.message}")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Catalog refresh failed", e)
            }
        } else if (refreshCatalog && remaining > 0) {
            SaleSyncLog.event(
                clientSaleId = null,
                status = SyncQueueEntity.STATUS_PENDING,
                result = "QUEUE_OPEN_$remaining",
                action = "defer_catalog",
            )
        }

        return Result(
            salesPushed = salesDrain.pushed,
            mutationsPushed = mutDrain.pushed,
            salesRemaining = salesDrain.remaining,
            mutationsRemaining = mutDrain.remaining,
            oldestPendingAgeMs = maxOf(salesDrain.oldestPendingAgeMs, mutDrain.oldestPendingAgeMs),
            catalogRefreshed = catalogOk,
            offline = false,
            authRequired = false,
            token = bearer,
        )
    }

    /** Pending/open count for UI (unknown when offline/auth gate skipped drain). */
    suspend fun countOpenOrZero(repo: SyncRepository, pipelineResult: Result): Int {
        if (pipelineResult.salesRemaining >= 0) return pipelineResult.openUploads
        return try {
            repo.getPendingSyncCount()
        } catch (_: Exception) {
            0
        }
    }
}

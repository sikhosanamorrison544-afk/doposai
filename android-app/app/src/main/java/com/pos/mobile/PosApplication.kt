package com.pos.mobile

import android.app.Application
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.pos.mobile.data.sync.SyncWorker
import java.util.concurrent.TimeUnit

class PosApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        setDefaultServerUrlIfNeeded()
        scheduleSync()
    }

    /**
     * Default API base URL from BuildConfig (your domain). When you move backend to cloud,
     * change DEFAULT_API_BASE_URL in build.gradle or set "base_url" in app settings.
     */
    private fun setDefaultServerUrlIfNeeded() {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        if (!prefs.contains("base_url")) {
            prefs.edit().putString("base_url", BuildConfig.DEFAULT_API_BASE_URL).apply()
        }
    }

    /**
     * Schedule background sync when network is available.
     * Runs at most every 15 minutes; constraint requires network.
     * In a full implementation, base URL and token would come from SharedPreferences or secure storage.
     */
    private fun scheduleSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .addTag("pos_sync")
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "pos_sync_work",
            ExistingPeriodicWorkPolicy.KEEP,
            request
        )
    }
}

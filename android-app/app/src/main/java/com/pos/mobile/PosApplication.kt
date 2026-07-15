package com.pos.mobile

import android.app.Application
import com.pos.mobile.sync.ConnectivitySyncMonitor
import com.pos.mobile.sync.SyncScheduler

class PosApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        setDefaultServerUrlIfNeeded()
        SyncScheduler.schedulePeriodic(this)
        ConnectivitySyncMonitor.register(this)
    }

    /**
     * Set default server URL on first install only. Do not overwrite a URL the user chose —
     * Android and desktop/web must point at the same backend to share sales and stock.
     */
    private fun setDefaultServerUrlIfNeeded() {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val current = prefs.getString("base_url", null)
        if (current.isNullOrBlank()) {
            prefs.edit().putString("base_url", BuildConfig.DEFAULT_API_BASE_URL).apply()
        }
    }
}

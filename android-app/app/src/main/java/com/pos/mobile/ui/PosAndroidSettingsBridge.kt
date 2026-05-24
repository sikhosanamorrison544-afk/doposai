package com.pos.mobile.ui

import android.content.Context
import android.webkit.JavascriptInterface
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.pos.mobile.BuildConfig
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.sync.SyncWorker
import org.json.JSONObject

/**
 * Keeps Android SharedPreferences in sync with server store settings (same DB as web).
 */
class PosAndroidSettingsBridge(private val context: Context) {

    @JavascriptInterface
    fun applyStoreSettings(json: String): String {
        return try {
            val o = JSONObject(json)
            context.getSharedPreferences("pos", Context.MODE_PRIVATE).edit()
                .putString("store_name", o.optString("store_name", "All In One POS"))
                .putString("store_phone", o.optString("store_phone", ""))
                .putString("store_location", o.optString("store_location", ""))
                .putString("store_settings_json", json)
                .apply()
            requestSettingsSync()
            JSONObject().put("ok", true).toString()
        } catch (e: Exception) {
            JSONObject().put("ok", false).put("error", e.message ?: "apply failed").toString()
        }
    }

    private fun requestSettingsSync() {
        val prefs = context.getSharedPreferences("pos", Context.MODE_PRIVATE)
        val token = SessionStore(context).getAccessToken() ?: prefs.getString("token", null) ?: return
        val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "pos_sync_settings",
            ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(constraints)
                .setInputData(
                    workDataOf(
                        SyncWorker.KEY_BASE_URL to baseUrl,
                        SyncWorker.KEY_TOKEN to token,
                        SyncWorker.KEY_FULL_CACHE to false,
                    ),
                )
                .build(),
        )
    }
}

package com.pos.mobile.ui

import android.content.Context
import android.webkit.JavascriptInterface
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.OfflineMutationEntity
import kotlinx.coroutines.runBlocking
import org.json.JSONObject

/**
 * Queues API mutations from WebView JavaScript when offline (with request body).
 */
class PosAndroidOfflineBridge(private val context: Context) {

    @JavascriptInterface
    fun isOnline(): Boolean {
        return com.pos.mobile.sync.NetworkUtils.isOnline(context)
    }

    @JavascriptInterface
    fun queueMutation(payloadJson: String): String {
        return runBlocking {
            try {
                val o = JSONObject(payloadJson)
                val method = o.getString("method")
                val path = o.getString("path")
                val body = o.optString("body", null).takeIf { it.isNotEmpty() }
                val contentType = o.optString("contentType", "application/json")
                val db = AppDatabase.getInstance(context)
                val id = db.offlineMutationDao().insert(
                    OfflineMutationEntity(
                        method = method,
                        path = path,
                        requestBody = body,
                        contentType = contentType,
                        createdAt = System.currentTimeMillis(),
                    ),
                )
                JSONObject()
                    .put("ok", true)
                    .put("queued", true)
                    .put("id", id)
                    .toString()
            } catch (e: Exception) {
                JSONObject()
                    .put("ok", false)
                    .put("error", e.message ?: "queue failed")
                    .toString()
            }
        }
    }

    @JavascriptInterface
    fun pendingCount(): Int {
        return runBlocking {
            AppDatabase.getInstance(context)
                .offlineMutationDao()
                .getByStatus(OfflineMutationEntity.STATUS_PENDING)
                .size
        }
    }
}

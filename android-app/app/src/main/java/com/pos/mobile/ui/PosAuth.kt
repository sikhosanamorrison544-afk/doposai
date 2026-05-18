package com.pos.mobile.ui

import android.content.Context
import com.pos.mobile.BuildConfig
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.data.sync.SyncWorker
import com.pos.mobile.sync.NetworkUtils
import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Response

object PosAuth {

    fun api(context: Context): ApiService {
        val baseUrl = prefs(context).getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL
        return SyncWorker.createApi(baseUrl)
    }

    fun prefs(context: Context) =
        context.getSharedPreferences("pos", Context.MODE_PRIVATE)

    fun bearer(context: Context): String? {
        val token = SessionStore(context).getAccessToken()
            ?: prefs(context).getString("token", null)
        return token?.let { "Bearer $it" }
    }

    fun role(context: Context): String =
        prefs(context).getString("role", "cashier") ?: "cashier"

    fun username(context: Context): String =
        prefs(context).getString("username", "") ?: ""

    fun requireOnline(context: Context): Boolean {
        if (!NetworkUtils.isOnline(context)) {
            return false
        }
        return !bearer(context).isNullOrBlank()
    }

    fun isAdmin(context: Context): Boolean = role(context) == "admin"

    /** Parse FastAPI error body for user-visible messages. */
    fun httpErrorDetail(res: Response<*>): String? {
        val raw = try {
            res.errorBody()?.string()
        } catch (_: Exception) {
            null
        } ?: return res.message().takeIf { !it.isNullOrBlank() }
        try {
            val root = JSONObject(raw)
            when (val detail = root.opt("detail")) {
                is String -> if (detail.isNotBlank()) return detail
                is JSONArray -> {
                    if (detail.length() > 0) {
                        val msg = detail.optJSONObject(0)?.optString("msg")?.trim()
                        if (!msg.isNullOrBlank()) {
                            return msg.removePrefix("Value error, ").trim()
                        }
                    }
                }
            }
        } catch (_: Exception) {
        }
        return raw.take(350)
    }
}

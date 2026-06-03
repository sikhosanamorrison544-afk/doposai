package com.pos.mobile.ui

import android.content.Context
import com.pos.mobile.BuildConfig
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.data.remote.RefreshRequest
import com.pos.mobile.data.sync.SyncWorker
import com.pos.mobile.sync.NetworkUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Response

/** Result of [PosAuth.ensureBearer] before an online-only API call (e.g. quotation PDF). */
sealed class BearerResult {
    data class Ok(val bearer: String) : BearerResult()
    object Missing : BearerResult()
    object Offline : BearerResult()
    object Expired : BearerResult()
}

object PosAuth {

    fun api(context: Context): ApiService {
        val baseUrl = prefs(context).getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL
        return SyncWorker.createApi(baseUrl)
    }

    fun prefs(context: Context) =
        context.getSharedPreferences("pos", Context.MODE_PRIVATE)

    fun rawToken(context: Context): String? {
        val token = SessionStore(context).getAccessToken()
            ?: prefs(context).getString("token", null)
        return token?.removePrefix("Bearer ")?.trim()?.takeIf { it.isNotBlank() }
    }

    fun bearer(context: Context): String? =
        rawToken(context)?.let { "Bearer $it" }

    /**
     * Returns a bearer token valid for online API calls. Verifies the access token and
     * refreshes it when expired (POS checkout can still work offline with a stale JWT).
     */
    suspend fun ensureBearer(context: Context): BearerResult = withContext(Dispatchers.IO) {
        if (!NetworkUtils.hasValidatedInternet(context)) {
            return@withContext BearerResult.Offline
        }
        var token = rawToken(context) ?: return@withContext BearerResult.Missing
        val session = SessionStore(context)
        val api = api(context)

        suspend fun verify(t: String): Boolean {
            val resp = api.authVerify("Bearer $t")
            return resp.isSuccessful && resp.body()?.valid == true
        }

        if (verify(token)) {
            return@withContext BearerResult.Ok("Bearer $token")
        }

        val refreshTok = session.getRefreshToken()
        if (!refreshTok.isNullOrBlank()) {
            val refreshResp = api.authRefresh(RefreshRequest(refreshTok))
            if (refreshResp.isSuccessful && refreshResp.body() != null) {
                val body = refreshResp.body()!!
                session.updateTokens(body.access_token, body.refresh_token)
                token = body.access_token
                if (verify(token)) {
                    return@withContext BearerResult.Ok("Bearer $token")
                }
            }
        }
        BearerResult.Expired
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

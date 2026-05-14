package com.pos.mobile.auth

import android.content.Context
import android.content.SharedPreferences
import android.util.Base64
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONObject

/**
 * Encrypted SaaS session (tokens + tenant + subscription metadata).
 * Mirrors access token into plain [prefsName] "token" for existing API code.
 */
class SessionStore(private val context: Context, private val prefsName: String = "pos") {

    private fun encryptedPrefs(): SharedPreferences? {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                "pos_saas_session",
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
        } catch (_: Exception) {
            null
        }
    }

    private fun plainPrefs(): SharedPreferences =
        context.getSharedPreferences(prefsName, Context.MODE_PRIVATE)

    fun clear() {
        encryptedPrefs()?.edit()?.clear()?.apply()
        plainPrefs().edit()
            .remove("token")
            .remove("username")
            .remove("role")
            .apply()
    }

    fun saveSession(
        accessToken: String,
        refreshToken: String,
        userId: Int,
        tenantId: Int?,
        tenantUid: String?,
        username: String,
        role: String,
        subscriptionStatus: String,
        lastVerifiedAtMs: Long?,
    ) {
        val enc = encryptedPrefs()
        if (enc != null) {
            enc.edit()
                .putString(KEY_ACCESS, accessToken)
                .putString(KEY_REFRESH, refreshToken)
                .putInt(KEY_USER_ID, userId)
                .putString(KEY_TENANT_UID, tenantUid ?: "")
                .putString(KEY_SUB, subscriptionStatus)
                .putLong(KEY_LAST_VERIFIED, lastVerifiedAtMs ?: System.currentTimeMillis())
                .apply()
            if (tenantId != null) {
                enc.edit().putInt(KEY_TENANT_ID, tenantId).apply()
            }
        }
        plainPrefs().edit()
            .putString("token", accessToken)
            .putString("username", username)
            .putString("role", role)
            .apply()
    }

    fun hasRefreshToken(): Boolean =
        !encryptedPrefs()?.getString(KEY_REFRESH, null).isNullOrBlank()

    fun getRefreshToken(): String? = encryptedPrefs()?.getString(KEY_REFRESH, null)

    fun getAccessToken(): String? =
        encryptedPrefs()?.getString(KEY_ACCESS, null) ?: plainPrefs().getString("token", null)

    fun subscriptionStatus(): String =
        encryptedPrefs()?.getString(KEY_SUB, "active") ?: "active"

    fun lastVerifiedAtMs(): Long =
        encryptedPrefs()?.getLong(KEY_LAST_VERIFIED, 0L) ?: 0L

    /**
     * Offline use: JWT exp must be in future, or within [graceSeconds] after exp if subscription was OK.
     */
    fun canUseOffline(graceSeconds: Long = 3 * 24 * 3600): Boolean {
        val token = getAccessToken() ?: return false
        val exp = JwtUtil.expiryEpochSeconds(token) ?: return false
        val now = System.currentTimeMillis() / 1000
        if (exp >= now) return true
        if (now <= exp + graceSeconds) {
            val sub = subscriptionStatus()
            return sub != "trial_expired" && sub != "canceled"
        }
        return false
    }

    fun updateTokens(access: String, refresh: String?) {
        encryptedPrefs()?.edit()?.apply {
            putString(KEY_ACCESS, access)
            if (refresh != null) putString(KEY_REFRESH, refresh)
            apply()
        }
        plainPrefs().edit().putString("token", access).apply()
    }

    fun updateSubscriptionMeta(status: String, verifiedMs: Long) {
        encryptedPrefs()?.edit()
            ?.putString(KEY_SUB, status)
            ?.putLong(KEY_LAST_VERIFIED, verifiedMs)
            ?.apply()
    }

    companion object {
        private const val KEY_ACCESS = "access_token"
        private const val KEY_REFRESH = "refresh_token"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_TENANT_ID = "tenant_id"
        private const val KEY_TENANT_UID = "tenant_uid"
        private const val KEY_SUB = "subscription_status"
        private const val KEY_LAST_VERIFIED = "last_verified_at"
    }
}

object JwtUtil {
    fun expiryEpochSeconds(jwt: String): Long? {
        val parts = jwt.split('.')
        if (parts.size < 2) return null
        val payload = parts[1]
        val decoded = try {
            val bytes = Base64.decode(payload, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
            String(bytes, Charsets.UTF_8)
        } catch (_: Exception) {
            return null
        }
        return try {
            JSONObject(decoded).optLong("exp", 0L).takeIf { it > 0 }
        } catch (_: Exception) {
            null
        }
    }
}

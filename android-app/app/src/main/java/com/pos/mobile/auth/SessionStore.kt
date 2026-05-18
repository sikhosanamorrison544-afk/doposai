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

    /** Extend offline POS window after a successful online login or sync. */
    fun recordOfflineAnchor() {
        val now = System.currentTimeMillis()
        encryptedPrefs()?.edit()?.putLong(KEY_OFFLINE_ANCHOR, now)?.apply()
        plainPrefs().edit().putLong(KEY_OFFLINE_ANCHOR_PLAIN, now).apply()
    }

    fun offlineAnchorMs(): Long =
        encryptedPrefs()?.getLong(KEY_OFFLINE_ANCHOR, 0L)?.takeIf { it > 0 }
            ?: plainPrefs().getLong(KEY_OFFLINE_ANCHOR_PLAIN, 0L)

    /**
     * POS may run offline for [offlineGraceMs] after last online login/sync (default 3 days),
     * in addition to JWT grace handled by [canUseOffline].
     */
    fun subscriptionEndMs(): Long =
        encryptedPrefs()?.getLong(KEY_SUB_END, 0L)?.takeIf { it > 0 } ?: 0L

    fun accessAllowedCached(): Boolean =
        encryptedPrefs()?.getBoolean(KEY_ACCESS, true) ?: true

    fun canUseOfflineForPos(offlineGraceMs: Long = OFFLINE_POS_GRACE_MS): Boolean {
        if (!hasUsableToken()) return false
        val sub = subscriptionStatus()
        val graceMs = offlineGraceMs
        val endMs = subscriptionEndMs()
        if (endMs > 0 && System.currentTimeMillis() < endMs + graceMs) {
            return true
        }
        if (!accessAllowedCached() && sub in listOf("expired", "trial_expired", "suspended")) {
            val verified = lastVerifiedAtMs()
            if (verified > 0 && System.currentTimeMillis() < verified + graceMs) return true
        }
        if (sub == "trial_expired" || sub == "canceled" || sub == "suspended") return false
        val anchor = offlineAnchorMs()
        if (anchor > 0 && System.currentTimeMillis() < anchor + offlineGraceMs) return true
        return canUseOffline(offlineGraceMs / 1000)
    }

    fun offlineRemainingMs(offlineGraceMs: Long = OFFLINE_POS_GRACE_MS): Long {
        val anchor = offlineAnchorMs()
        if (anchor <= 0) return 0L
        return (anchor + offlineGraceMs - System.currentTimeMillis()).coerceAtLeast(0L)
    }

    private fun hasUsableToken(): Boolean =
        !getAccessToken().isNullOrBlank() ||
            !plainPrefs().getString("token", null).isNullOrBlank()

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
                .putString(KEY_ACCESS_TOKEN, accessToken)
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
        recordOfflineAnchor()
    }

    fun hasRefreshToken(): Boolean =
        !encryptedPrefs()?.getString(KEY_REFRESH, null).isNullOrBlank()

    fun getRefreshToken(): String? = encryptedPrefs()?.getString(KEY_REFRESH, null)

    fun getAccessToken(): String? =
        encryptedPrefs()?.getString(KEY_ACCESS_TOKEN, null) ?: plainPrefs().getString("token", null)

    fun getUserId(): Int =
        encryptedPrefs()?.getInt(KEY_USER_ID, 0) ?: 0

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
            putString(KEY_ACCESS_TOKEN, access)
            if (refresh != null) putString(KEY_REFRESH, refresh)
            apply()
        }
        plainPrefs().edit().putString("token", access).apply()
    }

    fun updateSubscriptionMeta(status: String, verifiedMs: Long) {
        updateSubscriptionCache(status, null, null, verifiedMs, null)
    }

    fun updateSubscriptionCache(
        status: String,
        subscriptionEndIso: String?,
        plan: String?,
        verifiedMs: Long,
        accessAllowed: Boolean?,
    ) {
        val endMs = parseIsoToMs(subscriptionEndIso)
        encryptedPrefs()?.edit()?.apply {
            putString(KEY_SUB, status)
            putLong(KEY_LAST_VERIFIED, verifiedMs)
            if (endMs > 0) putLong(KEY_SUB_END, endMs)
            if (plan != null) putString(KEY_PLAN, plan)
            if (accessAllowed != null) putBoolean(KEY_ACCESS, accessAllowed)
            apply()
        }
    }

    private fun parseIsoToMs(iso: String?): Long {
        if (iso.isNullOrBlank()) return 0L
        return try {
            val trimmed = iso.replace("Z", "").substringBefore("+").trim()
            val format = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
            format.timeZone = java.util.TimeZone.getTimeZone("UTC")
            format.parse(trimmed)?.time ?: 0L
        } catch (_: Exception) {
            0L
        }
    }

    companion object {
        const val OFFLINE_POS_GRACE_MS = 3L * 24 * 60 * 60 * 1000
        private const val KEY_OFFLINE_ANCHOR = "offline_anchor_ms"
        private const val KEY_OFFLINE_ANCHOR_PLAIN = "offline_anchor_ms"
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_REFRESH = "refresh_token"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_TENANT_ID = "tenant_id"
        private const val KEY_TENANT_UID = "tenant_uid"
        private const val KEY_SUB = "subscription_status"
        private const val KEY_SUB_END = "subscription_end_ms"
        private const val KEY_PLAN = "subscription_plan"
        private const val KEY_ACCESS = "subscription_access_allowed"
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

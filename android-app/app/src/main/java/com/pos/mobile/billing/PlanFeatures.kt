package com.pos.mobile.billing

import android.content.Context

/**
 * Cached subscription feature flags from GET /api/subscriptions/status.
 * Trial effective plan is Pro server-side → all features in cache.
 */
object PlanFeatures {
    private const val PREFS = "pos"
    private const val KEY_FEATURES = "subscription_features"

    fun save(context: Context, features: List<String>?) {
        val set = features?.toSet() ?: emptySet()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putStringSet(KEY_FEATURES, set)
            .apply()
    }

    fun has(context: Context, feature: String): Boolean {
        val set = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet(KEY_FEATURES, null)
            ?: return true
        if (set.isEmpty()) return false
        return set.contains(feature)
    }

    fun menuFeatureForItemId(itemId: Int): String? = when (itemId) {
        com.pos.mobile.R.id.page_layby -> "layby"
        com.pos.mobile.R.id.page_pending_collection -> "pending_collection"
        com.pos.mobile.R.id.page_analytics -> "analytics"
        com.pos.mobile.R.id.page_withdrawals -> "withdrawals"
        com.pos.mobile.R.id.page_outstanding_debts -> "outstanding_debts"
        com.pos.mobile.R.id.page_quotations -> "quotations"
        else -> null
    }
}

package com.pos.mobile.sync

import android.net.Uri

object OfflineCacheKeys {
    fun forGet(path: String, query: String?): String {
        val normalizedPath = if (path.startsWith("/")) path else "/$path"
        val q = query
            ?.split("&")
            ?.filter { it.isNotBlank() && !it.startsWith("_t=") }
            ?.sorted()
            ?.joinToString("&")
        return if (q.isNullOrEmpty()) "GET|$normalizedPath" else "GET|$normalizedPath?$q"
    }

    fun forRequest(method: String, uri: Uri): String? {
        if (method != "GET") return null
        val path = uri.encodedPath ?: return null
        if (!isCacheablePath(path)) return null
        return forGet(path, uri.encodedQuery)
    }

    fun isCacheablePath(path: String): Boolean {
        if (path.startsWith("/api/")) return true
        return path in OFFLINE_HTML_PATHS
    }

    val OFFLINE_HTML_PATHS = setOf(
        "/pending-collection",
        "/analytics",
        "/withdrawals/history",
        "/debts/outstanding",
        "/layby",
        "/admin",
        "/store-settings",
        "/accounting",
        "/customer-history",
        "/transaction-payment-history",
        "/quotations",
    )
}

package com.pos.mobile.sync

/**
 * API paths and web pages pulled from the Render master DB on each login / background sync.
 */
object MasterSyncEndpoints {
    /** Small JSON endpoints only — large lists (layby, customers) are pulled on demand in WebView. */
    fun apiPathsForSync(): List<String> = listOf(
        "/api/sales/pending-collection",
        "/api/debts/outstanding",
        "/api/notifications",
        "/api/shifts/active",
    )

    /** HTML pages are loaded on demand in WebView — do not bulk-prefetch in background sync. */
    val webPages: List<String> = emptyList()
}

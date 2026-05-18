package com.pos.mobile.sync

import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * API paths and web pages pulled from the Render master DB on each login / background sync.
 */
object MasterSyncEndpoints {
    private val dateFmt = DateTimeFormatter.ISO_LOCAL_DATE

    fun apiPathsForSync(today: LocalDate = LocalDate.now()): List<String> {
        val monthStart = today.withDayOfMonth(1)
        val from = monthStart.format(dateFmt)
        val to = today.format(dateFmt)
        return listOf(
            "/api/products",
            "/api/customers",
            "/api/store-settings",
            "/api/sales/pending-collection",
            "/api/debts/outstanding",
            "/api/withdrawals?limit=1000",
            "/api/layby/customers",
            "/api/layby/transactions",
            "/api/analytics/dashboard?days=30",
            "/api/analytics/revenue-per-product?days=30&limit=20",
            "/api/analytics/zero-sales?days=30",
            "/api/notifications",
            "/api/shifts/active",
            "/api/shifts?limit=50",
            "/api/reports/summary?from_date=$from&to_date=$to",
            "/api/accounting/trial-balance",
            "/api/accounting/fixed-assets",
            "/api/accounting/profit-loss?start_date=$from&end_date=$to",
            "/api/accounting/balance-sheet?as_of_date=$to",
            "/api/accounting/vat-report?start_date=$from&end_date=$to",
        )
    }

    val webPages: List<String> = listOf(
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

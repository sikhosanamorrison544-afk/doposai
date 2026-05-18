package com.pos.mobile.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.chip.ChipGroup
import com.pos.mobile.R
import com.pos.mobile.data.remote.AnalyticsDashboardDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class StatsActivity : BaseNativeActivity() {

    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var messageTv: TextView
    private var periodDays = 30

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.stats_title), R.layout.activity_stats)
        refresh = findViewById(R.id.stats_refresh)
        messageTv = findViewById(R.id.stats_message)
        refresh.setColorSchemeColors(ContextCompat.getColor(this, R.color.primary))

        findViewById<ChipGroup>(R.id.stats_period_chips).setOnCheckedStateChangeListener { _, checkedIds ->
            periodDays = when (checkedIds.firstOrNull()) {
                R.id.chip_7d -> 7
                R.id.chip_90d -> 90
                else -> 30
            }
            loadDashboard()
        }

        refresh.setOnRefreshListener { loadDashboard() }
        findViewById<Button>(R.id.btn_open_accounting).setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/accounting")
                putExtra(WebViewActivity.EXTRA_TITLE, getString(R.string.stats_open_accounting))
            })
        }
        findViewById<Button>(R.id.btn_open_analytics_web).setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/analytics")
                putExtra(WebViewActivity.EXTRA_TITLE, getString(R.string.stats_open_analytics_web))
            })
        }
        loadDashboard()
    }

    private fun loadDashboard() {
        if (!PosAuth.requireOnline(this)) {
            refresh.isRefreshing = false
            NativeUi.bindMessage(messageTv, getString(R.string.stats_requires_network))
            return
        }
        refresh.isRefreshing = true
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@StatsActivity) ?: run {
                refresh.isRefreshing = false
                return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@StatsActivity).getAnalyticsDashboard(bearer, days = periodDays)
                }
                if (!resp.isSuccessful) {
                    NativeUi.bindMessage(messageTv, resp.message() ?: "Failed to load statistics")
                    return@launch
                }
                bindDashboard(resp.body())
                NativeUi.bindMessage(messageTv, null)
            } catch (e: Exception) {
                NativeUi.bindMessage(messageTv, e.message ?: "Failed to load statistics")
            } finally {
                refresh.isRefreshing = false
            }
        }
    }

    private fun bindDashboard(data: AnalyticsDashboardDto?) {
        val summary = data?.summary
        findViewById<TextView>(R.id.stats_revenue).text =
            NativeUi.formatMoney(summary?.total_revenue ?: 0.0)
        findViewById<TextView>(R.id.stats_products_sold).text =
            (summary?.total_products_sold ?: 0).toString()
        findViewById<TextView>(R.id.stats_active_products).text =
            (summary?.total_active_products ?: 0).toString()
        findViewById<TextView>(R.id.stats_zero_sales).text =
            (summary?.zero_sales_count ?: 0).toString()

        val top = data?.top_selling
        findViewById<TextView>(R.id.stats_top_product).text = productLine(top?.product_name, top?.quantity_sold, top?.revenue)

        val least = data?.least_selling
        findViewById<TextView>(R.id.stats_least_product).text =
            productLine(least?.product_name, least?.quantity_sold, least?.revenue)
    }

    private fun productLine(name: String?, qty: Int?, revenue: Double?): String {
        if (name.isNullOrBlank()) return getString(R.string.stats_no_product)
        return getString(
            R.string.stats_product_line,
            name,
            qty ?: 0,
            NativeUi.formatMoney(revenue ?: 0.0),
        )
    }
}

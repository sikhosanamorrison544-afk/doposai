package com.pos.mobile.ui

import android.os.Bundle
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import androidx.viewpager2.adapter.FragmentStateAdapter
import com.google.android.material.tabs.TabLayoutMediator
import com.pos.mobile.R
import com.pos.mobile.data.remote.LaybyCustomerDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LaybyActivity : BaseNativeActivity() {

    private lateinit var refresh: SwipeRefreshLayout
    private var payFragment: LaybyPayFragment? = null
    private var customers: List<LaybyCustomerDto> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.layby_title), R.layout.activity_layby)
        refresh = findViewById(R.id.layby_refresh)
        refresh.setColorSchemeColors(ContextCompat.getColor(this, R.color.layby_blue))

        val pager = findViewById<androidx.viewpager2.widget.ViewPager2>(R.id.layby_pager)
        val tabs = findViewById<com.google.android.material.tabs.TabLayout>(R.id.layby_tabs)
        val adapter = LaybyPagerAdapter(this)
        pager.adapter = adapter
        TabLayoutMediator(tabs, pager) { tab, position ->
            tab.text = when (position) {
                0 -> getString(R.string.layby_tab_payment)
                else -> getString(R.string.layby_tab_new_customer)
            }
        }.attach()

        refresh.setOnRefreshListener { reloadCustomers() }
        reloadCustomers()
    }

    fun reloadCustomers() {
        if (!PosAuth.requireOnline(this)) {
            refresh.isRefreshing = false
            return
        }
        refresh.isRefreshing = true
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@LaybyActivity) ?: run {
                refresh.isRefreshing = false
                return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@LaybyActivity).getLaybyCustomers(bearer)
                }
                customers = if (resp.isSuccessful) resp.body().orEmpty() else emptyList()
                payFragment?.setCustomers(customers)
            } catch (_: Exception) {
                customers = emptyList()
                payFragment?.setCustomers(emptyList())
            } finally {
                refresh.isRefreshing = false
            }
        }
    }

    private inner class LaybyPagerAdapter(fa: FragmentActivity) : FragmentStateAdapter(fa) {
        override fun getItemCount(): Int = 2

        override fun createFragment(position: Int): Fragment = when (position) {
            0 -> LaybyPayFragment().also {
                payFragment = it
                if (customers.isNotEmpty()) it.setCustomers(customers)
            }
            else -> LaybyNewCustomerFragment()
        }
    }
}

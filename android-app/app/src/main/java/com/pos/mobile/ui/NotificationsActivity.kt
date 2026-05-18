package com.pos.mobile.ui

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.pos.mobile.R
import com.pos.mobile.data.remote.NotificationDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class NotificationsActivity : BaseNativeActivity() {

    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var list: RecyclerView
    private lateinit var emptyTv: TextView
    private lateinit var adapter: NotificationAdapter
    private var items: List<NotificationDto> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.notifications_title), R.layout.activity_notifications)
        refresh = findViewById(R.id.notifications_refresh)
        list = findViewById(R.id.notifications_list)
        emptyTv = findViewById(R.id.notifications_empty)
        refresh.setColorSchemeColors(ContextCompat.getColor(this, R.color.primary))

        adapter = NotificationAdapter { markRead(it) }
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = adapter

        findViewById<Button>(R.id.btn_mark_all_read).setOnClickListener { markAllRead() }
        refresh.setOnRefreshListener { loadNotifications() }
        loadNotifications()
    }

    private fun loadNotifications() {
        if (!PosAuth.requireOnline(this)) {
            refresh.isRefreshing = false
            NativeUi.showError(this, getString(R.string.notifications_requires_network))
            return
        }
        refresh.isRefreshing = true
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@NotificationsActivity) ?: run {
                refresh.isRefreshing = false
                return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@NotificationsActivity).getNotifications(bearer)
                }
                items = if (resp.isSuccessful) resp.body().orEmpty() else emptyList()
                adapter.submit(items)
                emptyTv.isVisible = items.isEmpty()
                list.isVisible = items.isNotEmpty()
            } catch (e: Exception) {
                NativeUi.showError(this@NotificationsActivity, e.message ?: "Failed to load")
            } finally {
                refresh.isRefreshing = false
            }
        }
    }

    private fun markRead(notification: NotificationDto) {
        if (!PosAuth.requireOnline(this)) return
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@NotificationsActivity) ?: return@launch
            try {
                withContext(Dispatchers.IO) {
                    PosAuth.api(this@NotificationsActivity).markNotificationRead(bearer, notification.id)
                }
                items = items.map { if (it.id == notification.id) it.copy(is_read = true) else it }
                adapter.submit(items)
                setResult(RESULT_OK)
            } catch (_: Exception) {
            }
        }
    }

    private fun markAllRead() {
        if (!PosAuth.requireOnline(this)) {
            NativeUi.showError(this, getString(R.string.notifications_requires_network))
            return
        }
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@NotificationsActivity) ?: return@launch
            try {
                withContext(Dispatchers.IO) {
                    PosAuth.api(this@NotificationsActivity).markAllNotificationsRead(bearer)
                }
                items = items.map { it.copy(is_read = true) }
                adapter.submit(items)
                setResult(RESULT_OK)
            } catch (e: Exception) {
                NativeUi.showError(this@NotificationsActivity, e.message ?: "Failed")
            }
        }
    }
}

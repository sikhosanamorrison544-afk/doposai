package com.pos.mobile.sync

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.util.Log

/**
 * App-scoped network watcher so pending uploads are enqueued even when MainActivity
 * is not in the foreground.
 */
object ConnectivitySyncMonitor {
    private const val TAG = "ConnectivitySyncMonitor"
    @Volatile private var registered = false
    private var callback: ConnectivityManager.NetworkCallback? = null

    fun register(context: Context) {
        if (registered) return
        val app = context.applicationContext
        val cm = app.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.i(TAG, "Network available — scheduling pending sync drain")
                SyncScheduler.enqueueStickyDrain(app)
                SyncScheduler.enqueueAfterSaleOrReconnect(app)
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) &&
                    caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                ) {
                    SyncScheduler.enqueueStickyDrain(app)
                }
            }
        }
        try {
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build()
            cm.registerNetworkCallback(request, cb)
            callback = cb
            registered = true
            if (NetworkUtils.hasValidatedInternet(app)) {
                SyncScheduler.enqueueStickyDrain(app)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to register connectivity callback", e)
        }
    }
}

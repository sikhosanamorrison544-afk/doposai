package com.pos.mobile.sync

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

object NetworkUtils {

    /** Basic link present (may be captive portal or unusable). */
    fun isOnline(context: Context): Boolean {
        val caps = activeCapabilities(context) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /** Internet verified by the OS (DNS/connectivity check passed). */
    fun hasValidatedInternet(context: Context): Boolean {
        val caps = activeCapabilities(context) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    /**
     * Strong enough link for catalog/cache pulls (Wi‑Fi, Ethernet, or unmetered).
     * Avoids heavy sync on weak mobile links.
     */
    fun isGoodNetworkForHeavySync(context: Context): Boolean {
        val caps = activeCapabilities(context) ?: return false
        if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) return false
        if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) return false
        if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED)) return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) ||
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    }

    /** Any validated network — OK for uploading queued sales (small payloads). */
    fun canSyncPendingSales(context: Context): Boolean = hasValidatedInternet(context)

    private fun activeCapabilities(context: Context): NetworkCapabilities? {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return null
        return cm.getNetworkCapabilities(network)
    }
}

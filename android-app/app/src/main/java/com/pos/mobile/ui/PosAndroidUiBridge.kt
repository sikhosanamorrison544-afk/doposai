package com.pos.mobile.ui

import android.content.Intent
import android.net.Uri
import android.webkit.JavascriptInterface
import androidx.appcompat.app.AppCompatActivity

/** WebView bridge: open full web pages in the device browser. */
class PosAndroidUiBridge(
    private val activity: AppCompatActivity,
) {
    @JavascriptInterface
    fun openExternalUrl(url: String) {
        activity.runOnUiThread {
            try {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url.trim()))
                activity.startActivity(intent)
            } catch (_: Exception) {
                // ignore — page may fall back to window.open
            }
        }
    }
}

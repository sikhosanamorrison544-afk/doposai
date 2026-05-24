package com.pos.mobile.ui

import android.content.Context
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.sync.NetworkUtils
import com.pos.mobile.sync.OfflineCacheKeys
import kotlinx.coroutines.runBlocking
import java.io.ByteArrayInputStream
import java.nio.charset.StandardCharsets

/**
 * Serves cached API snapshots when offline. Mutations use offline-fetch.js (with POST body).
 */
class OfflineWebViewClient(
    private val context: Context,
    private val baseUrl: String,
    private val delegate: WebViewClient,
) : WebViewClient() {

    private val db by lazy { AppDatabase.getInstance(context) }

    override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
        val req = request ?: return delegate.shouldInterceptRequest(view, request)
        val uri = req.url ?: return delegate.shouldInterceptRequest(view, request)
        if (!isOurOrigin(uri)) return delegate.shouldInterceptRequest(view, request)

        if (!NetworkUtils.isOnline(context)) {
            if (req.method == "GET") {
                loadCachedGet(uri)?.let { return it }
            }
            // POST/PUT/PATCH/DELETE: handled by offline-fetch.js + PosAndroidOffline (needs body).
        }
        return delegate.shouldInterceptRequest(view, request)
    }

    override fun onPageFinished(view: WebView?, url: String?) {
        delegate.onPageFinished(view, url)
        if (!NetworkUtils.isOnline(context) && view != null) {
            view.evaluateJavascript(OFFLINE_BANNER_JS, null)
        }
    }

    private fun isOurOrigin(uri: Uri): Boolean {
        val baseHost = Uri.parse(baseUrl.trimEnd('/')).host ?: return false
        return uri.host?.equals(baseHost, ignoreCase = true) == true
    }

    private fun loadCachedGet(uri: Uri): WebResourceResponse? = runBlocking {
        val key = OfflineCacheKeys.forRequest("GET", uri) ?: return@runBlocking null
        val entry = db.apiCacheDao().get(key) ?: return@runBlocking null
        val mime = entry.contentType.substringBefore(';').trim()
        val encoding = if (mime.startsWith("text/")) "utf-8" else null
        WebResourceResponse(
            mime,
            encoding,
            entry.statusCode,
            "OK",
            mapOf("Access-Control-Allow-Origin" to "*"),
            ByteArrayInputStream(entry.responseBody.toByteArray(StandardCharsets.UTF_8)),
        )
    }

    companion object {
        private val OFFLINE_BANNER_JS = """
            (function(){
              if(document.getElementById('pos-offline-banner')) return;
              var b=document.createElement('div');
              b.id='pos-offline-banner';
              b.textContent='Offline — showing last synced data';
              b.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99999;background:#b45309;color:#fff;padding:8px 12px;text-align:center;font-size:14px;font-family:sans-serif;';
              document.body.prepend(b);
            })();
        """.trimIndent()
    }
}

package com.pos.mobile.ui

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.CookieManager
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import com.pos.mobile.BuildConfig
import com.pos.mobile.R
import org.json.JSONObject

/**
 * Loads a page from the parent POS server so the app replicates every page exactly.
 * Injects the app's auth token into the WebView so Admin/Settings etc. work without
 * asking for login again (web pages use pos_token / pos_user in localStorage).
 */
class WebViewActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_PATH = "path"
        const val EXTRA_TITLE = "title"
    }

    private lateinit var baseUrl: String
    private lateinit var webView: WebView
    /** URL we are loading; when it finishes we inject auth into that origin then reload so the page sees the token. */
    private var injectThenReloadUrl: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_webview)

        val toolbar = findViewById<com.google.android.material.appbar.MaterialToolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL

        val path = intent.getStringExtra(EXTRA_PATH) ?: "/"
        val titleText = intent.getStringExtra(EXTRA_TITLE) ?: path.trimStart('/').ifEmpty { "POS" }
        supportActionBar?.title = titleText.replaceFirstChar { it.uppercase() }

        val url = baseUrl.trimEnd('/') + path
        val token = prefs.getString("token", null)
        val username = prefs.getString("username", "") ?: ""
        val role = prefs.getString("role", "cashier") ?: "cashier"

        webView = findViewById<WebView>(R.id.webview)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            cacheMode = WebSettings.LOAD_NO_CACHE
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            useWideViewPort = true
            loadWithOverviewMode = true
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, loadedUrl: String?) {
                val pending = injectThenReloadUrl
                if (pending != null && view != null && loadedUrl == pending) {
                    injectThenReloadUrl = null
                    injectAuthThenReload(view, pending, token, username, role)
                }
            }
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        if (!token.isNullOrBlank() && path != "/" && path.isNotBlank()) {
            injectThenReloadUrl = url
            webView.loadUrl(url)
        } else {
            webView.loadUrl(url)
        }
    }

    /**
     * Inject token into the current page's origin (so it's the POS server origin, not about:blank),
     * then reload the page so it loads with token already in localStorage and does not show login.
     */
    private fun injectAuthThenReload(webView: WebView, targetUrl: String, token: String?, username: String, role: String) {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val theme = prefs.getString("theme", "default") ?: "default"
        if (token.isNullOrBlank()) {
            val themeOnlyScript = "(function(){try{localStorage.setItem('pos-theme',${JSONObject.quote(theme)});}catch(e){}})();"
            webView.evaluateJavascript(themeOnlyScript) { }
            return
        }
        val userJson = JSONObject().apply {
            put("username", username)
            put("role", role)
        }.toString()
        val script = """
            (function() {
                try {
                    localStorage.setItem('pos_token', ${JSONObject.quote(token)});
                    localStorage.setItem('pos_user', ${JSONObject.quote(userJson)});
                    localStorage.setItem('pos-theme', ${JSONObject.quote(theme)});
                } catch (e) {}
            })();
        """.trimIndent()
        webView.evaluateJavascript(script) {
            webView.loadUrl(targetUrl)
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.pos_pages_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            finish()
            return true
        }
        when (item.itemId) {
            R.id.page_store -> {
                startActivity(Intent(this, MainActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                })
                finish()
                return true
            }
            R.id.page_admin -> loadPage("/admin", "Admin")
            R.id.page_layby -> loadPage("/layby", "Layby")
            R.id.page_pending_collection -> loadPage("/pending-collection", "Pending Collection")
            R.id.page_store_settings -> loadPage("/store-settings", "Store Settings")
            R.id.page_analytics -> loadPage("/analytics", "Analytics")
            R.id.page_accounting -> loadPage("/accounting", "Accounting")
            R.id.page_withdrawals -> loadPage("/withdrawals/history", "Withdrawals History")
            R.id.page_outstanding_debts -> loadPage("/debts/outstanding", "Outstanding Debts")
        }
        return super.onOptionsItemSelected(item)
    }

    private fun loadPage(path: String, title: String) {
        supportActionBar?.title = title
        val url = baseUrl.trimEnd('/') + path
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val token = prefs.getString("token", null)
        val username = prefs.getString("username", "") ?: ""
        val role = prefs.getString("role", "cashier") ?: "cashier"
        if (!token.isNullOrBlank()) {
            injectAuthThenNavigate(webView, url, token, username, role)
        } else {
            webView.loadUrl(url)
        }
    }

    /** Inject auth into current page (same origin as target) then navigate to targetUrl. Use when already on a POS page (e.g. menu). */
    private fun injectAuthThenNavigate(webView: WebView, targetUrl: String, token: String?, username: String, role: String) {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val theme = prefs.getString("theme", "default") ?: "default"
        if (token.isNullOrBlank()) {
            webView.loadUrl(targetUrl)
            return
        }
        val userJson = JSONObject().apply {
            put("username", username)
            put("role", role)
        }.toString()
        val script = """
            (function() {
                try {
                    localStorage.setItem('pos_token', ${JSONObject.quote(token)});
                    localStorage.setItem('pos_user', ${JSONObject.quote(userJson)});
                    localStorage.setItem('pos-theme', ${JSONObject.quote(theme)});
                } catch (e) {}
            })();
        """.trimIndent()
        webView.evaluateJavascript(script) {
            webView.loadUrl(targetUrl)
        }
    }
}

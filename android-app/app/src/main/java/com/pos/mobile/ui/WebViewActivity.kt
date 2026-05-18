package com.pos.mobile.ui

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.pos.mobile.BuildConfig
import com.pos.mobile.R
import com.pos.mobile.printer.BluetoothPermissionDelegate
import com.pos.mobile.printer.PrinterPermissionHelper
import com.pos.mobile.printer.PrinterSetupDialog
import com.pos.mobile.printer.bluetoothPermissionDelegate
import com.pos.mobile.printer.WebViewPrintSupport
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
        private const val FILE_CHOOSER_REQUEST = 2002

        /** MIME types so CSV exports from Sheets/Drive/files are not greyed out in the picker. */
        private val IMPORT_FILE_MIME_TYPES = arrayOf(
            "text/csv",
            "text/comma-separated-values",
            "application/csv",
            "application/vnd.ms-excel",
            "text/plain",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
            "*/*",
        )

        private fun buildImportFileChooserIntent(
            params: WebChromeClient.FileChooserParams?,
        ): Intent {
            // Do not use params.createIntent() alone — its accept filter often blocks .csv on Android.
            return Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                putExtra(Intent.EXTRA_MIME_TYPES, IMPORT_FILE_MIME_TYPES)
                if (params?.mode == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                }
            }
        }
    }

    private lateinit var baseUrl: String
    private lateinit var webView: WebView
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    /** URL we are loading; when it finishes we inject auth into that origin then reload so the page sees the token. */
    private var injectThenReloadUrl: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BluetoothPermissionDelegate.install(this)
        setContentView(R.layout.activity_webview)
        applyEdgeToEdgeInsets(findViewById(R.id.webview_root))

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
            cacheMode = WebSettings.LOAD_CACHE_ELSE_NETWORK
            databaseEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            useWideViewPort = true
            loadWithOverviewMode = true
        }
        WebViewPrintSupport.attach(this, webView)
        val authClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, loadedUrl: String?) {
                if (view != null) {
                    WebViewPrintSupport.injectHelper(view)
                    injectAndroidWebUiHints(view)
                }
                val pending = injectThenReloadUrl
                if (pending != null && view != null && loadedUrl == pending) {
                    injectThenReloadUrl = null
                    injectAuthThenReload(view, pending, token, username, role)
                }
            }
        }
        webView.webViewClient = OfflineWebViewClient(this, baseUrl, authClient)
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView?,
                callback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?,
            ): Boolean {
                filePathCallback?.onReceiveValue(null)
                filePathCallback = callback
                val intent = buildImportFileChooserIntent(params)
                return try {
                    @Suppress("DEPRECATION")
                    startActivityForResult(
                        Intent.createChooser(intent, getString(R.string.choose_import_file)),
                        FILE_CHOOSER_REQUEST,
                    )
                    true
                } catch (_: ActivityNotFoundException) {
                    filePathCallback?.onReceiveValue(null)
                    filePathCallback = null
                    false
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
    private fun injectAndroidWebUiHints(webView: WebView) {
        val script = """
            (function() {
                document.documentElement.classList.add('pos-android-app');
                if (document.body) document.body.classList.add('pos-android-app');
                try { localStorage.setItem('pos_android_app', '1'); } catch (e) {}
                if (typeof window.markPosAndroidApp === 'function') window.markPosAndroidApp();
                if (typeof window.initAdminAndroidUi === 'function') window.initAdminAndroidUi();
                if (typeof window.initPosAndroidPageUi === 'function') window.initPosAndroidPageUi();
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }

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
        menuInflater.inflate(R.menu.webview_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            finish()
            return true
        }
        if (item.itemId == R.id.action_printer) {
            val prefs = getSharedPreferences("pos", MODE_PRIVATE)
            val storeName = prefs.getString("store_name", getString(R.string.store_name))
                ?: getString(R.string.store_name)
            PrinterSetupDialog.show(this, lifecycleScope, storeName)
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

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == FILE_CHOOSER_REQUEST) {
            val callback = filePathCallback
            filePathCallback = null
            val uris = WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            callback?.onReceiveValue(uris)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PrinterPermissionHelper.REQUEST_CODE) {
            val prefs = getSharedPreferences("pos", MODE_PRIVATE)
            val storeName = prefs.getString("store_name", getString(R.string.store_name))
                ?: getString(R.string.store_name)
            val granted = PrinterPermissionHelper.legacyResultsGranted(permissions, grantResults)
            PrinterSetupDialog.handleBluetoothPermissionResult(
                activity = this,
                granted = granted,
                scope = lifecycleScope,
                storeName = storeName,
            )
        }
    }
}

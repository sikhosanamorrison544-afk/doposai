package com.pos.mobile.ui

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.CookieManager
import androidx.activity.result.contract.ActivityResultContracts
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
import com.pos.mobile.billing.PlanFeatures
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
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                putExtra(Intent.EXTRA_MIME_TYPES, IMPORT_FILE_MIME_TYPES)
                if (params?.mode == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                }
            }
        }
    }

    private lateinit var baseUrl: String
    private lateinit var webView: WebView
    private lateinit var importBridge: PosAndroidImportBridge
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private lateinit var importFileLauncher: androidx.activity.result.ActivityResultLauncher<Intent>
    /** URL we are loading; when it finishes we inject auth into that origin then reload so the page sees the token. */
    private var injectThenReloadUrl: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        importFileLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            handleImportFileChooserResult(result.resultCode, result.data)
        }
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
        importBridge = PosAndroidImportBridge(this)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            cacheMode = WebSettings.LOAD_CACHE_ELSE_NETWORK
            databaseEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            useWideViewPort = true
            loadWithOverviewMode = true
            val baseUa = userAgentString ?: ""
            if (!baseUa.contains("DoPosPOS-Android")) {
                userAgentString = "$baseUa DoPosPOS-Android/1"
            }
        }
        WebViewPrintSupport.attach(this, webView, importBridge)
        val authClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, loadedUrl: String?) {
                if (view != null) {
                    WebViewPrintSupport.injectHelper(view)
                    injectAndroidWebUiHints(view)
                    injectOfflineFetchScript(view)
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
                    importFileLauncher.launch(
                        Intent.createChooser(intent, getString(R.string.choose_import_file)),
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
                window.__POS_ANDROID_WEBVIEW__ = true;
                if (typeof window.markPosAndroidWebView === 'function') window.markPosAndroidWebView();
                else if (typeof window.markPosAndroidApp === 'function') window.markPosAndroidApp();
                if (typeof window.initAdminAndroidUi === 'function') window.initAdminAndroidUi();
                if (typeof window.initPosAndroidPageUi === 'function') window.initPosAndroidPageUi();
                if (typeof window.renderAdminProductsMobile === 'function' && window.adminProducts && window.adminProducts.length) {
                    window.renderAdminProductsMobile(window.adminProducts);
                }
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }

    private fun injectOfflineFetchScript(webView: WebView) {
        val scriptUrl = baseUrl.trimEnd('/') + "/static/js/offline-fetch.js?v=1"
        val script = """
            (function() {
                if (window.__posOfflineFetchLoaded) return;
                var s = document.createElement('script');
                s.src = ${org.json.JSONObject.quote(scriptUrl)};
                s.onload = function() { window.__posOfflineFetchLoaded = true; };
                document.head.appendChild(s);
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
        for (i in 0 until menu.size()) {
            val item = menu.getItem(i)
            val feat = PlanFeatures.menuFeatureForItemId(item.itemId) ?: continue
            item.isVisible = PlanFeatures.has(this, feat)
        }
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
        PlanFeatures.menuFeatureForItemId(item.itemId)?.let { feat ->
            if (!PlanFeatures.has(this, feat)) {
                android.widget.Toast.makeText(
                    this,
                    getString(R.string.plan_feature_locked),
                    android.widget.Toast.LENGTH_LONG,
                ).show()
                return true
            }
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

    private fun parseFileChooserUris(resultCode: Int, data: Intent?): Array<Uri>? {
        if (resultCode != RESULT_OK) return null
        val fromParser = WebChromeClient.FileChooserParams.parseResult(resultCode, data)
        if (!fromParser.isNullOrEmpty()) return fromParser
        if (data == null) return null
        val clip = data.clipData
        if (clip != null && clip.itemCount > 0) {
            return Array(clip.itemCount) { clip.getItemAt(it).uri }
        }
        return data.data?.let { arrayOf(it) }
    }

    private fun notifyWebViewImportFileSelected(fileName: String) {
        val quoted = JSONObject.quote(fileName)
        val script = """
            (function() {
                window.__posAndroidImportReady = true;
                window.__posAndroidImportFileName = $quoted;
                if (typeof window.onPosAndroidImportFileReady === 'function') {
                    window.onPosAndroidImportFileReady($quoted);
                }
            })();
        """.trimIndent()
        webView.post { webView.evaluateJavascript(script, null) }
    }

    private fun handleImportFileChooserResult(resultCode: Int, data: Intent?) {
        val callback = filePathCallback
        filePathCallback = null
        val uris = parseFileChooserUris(resultCode, data)
        val uri = uris?.firstOrNull()

        if (uri != null) {
            try {
                grantUriPermission(
                    packageName,
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            } catch (_: Exception) {
                // ignore
            }
            try {
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            } catch (_: SecurityException) {
                // one-time read from picker is still OK
            }
            val name = importBridge.resolveDisplayName(uri)
            importBridge.setPendingImport(uri, name)
            notifyWebViewImportFileSelected(name)
        } else {
            importBridge.clearPendingImport()
            webView.post {
                webView.evaluateJavascript(
                    "(function(){window.__posAndroidImportReady=false;})();",
                    null,
                )
            }
        }

        // Satisfy WebView file input (may fire empty change — JS ignores when native pending is set)
        callback?.onReceiveValue(uris)
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

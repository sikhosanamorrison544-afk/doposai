package com.pos.mobile.ui

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.ConnectivityManager
import android.net.ConnectivityManager.NetworkCallback
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Bundle
import android.text.InputType
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.pos.mobile.BuildConfig
import com.pos.mobile.R
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.ProductEntity
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.remote.ApiService
import com.pos.mobile.data.remote.AuthResponseDto
import com.pos.mobile.data.remote.ForgotPasswordRequest
import com.pos.mobile.data.remote.LoginEmailRequest
import com.pos.mobile.data.remote.LogoutRequest
import com.pos.mobile.data.remote.RefreshRequest
import com.pos.mobile.data.remote.RegisterRequest
import com.pos.mobile.data.remote.ResetPasswordRequest
import com.pos.mobile.data.sync.SyncWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Response
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class MainActivity : AppCompatActivity() {

    private lateinit var viewModel: PosViewModel
    private lateinit var cartAdapter: CartAdapter
    private lateinit var searchAdapter: SearchProductAdapter
    private var api: ApiService? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        applyEdgeToEdgeInsets(findViewById(R.id.root_container))
        viewModel = androidx.lifecycle.ViewModelProvider(this)[PosViewModel::class.java]

        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        applyThemeToRoot(prefs)
        val loginContainer = findViewById<View>(R.id.login_container)
        val posContainer = findViewById<View>(R.id.pos_container)

        lifecycleScope.launch {
            val session = SessionStore(this@MainActivity)
            val tokenPresent = !prefs.getString("token", null).isNullOrBlank()
            val cachedProducts = withContext(Dispatchers.IO) {
                AppDatabase.getInstance(this@MainActivity).productDao().countActive() > 0
            }
            val offlineOk = session.canUseOffline() && tokenPresent && cachedProducts
            val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: BuildConfig.DEFAULT_API_BASE_URL
            if (offlineOk) {
                api = SyncWorker.createApi(baseUrl)
                loginContainer.isVisible = false
                posContainer.isVisible = true
                Toast.makeText(
                    this@MainActivity,
                    getString(R.string.offline_auth_indicator),
                    Toast.LENGTH_LONG
                ).show()
                setupPos(posContainer, prefs)
                refreshSessionInBackground(prefs)
            } else {
                loginContainer.isVisible = true
                posContainer.isVisible = false
                setupLogin(prefs, loginContainer, posContainer)
            }
        }
    }

    private fun setupLogin(
        prefs: android.content.SharedPreferences,
        loginContainer: View,
        posContainer: View
    ) {
        val loginTitle = findViewById<TextView>(R.id.login_screen_title)
        val loginCard = findViewById<View>(R.id.login_form_card)
        val registerCard = findViewById<View>(R.id.register_form_card)
        val username = findViewById<EditText>(R.id.login_username)
        val password = findViewById<EditText>(R.id.login_password)
        val loginButton = findViewById<android.widget.Button>(R.id.login_button)
        val loginError = findViewById<TextView>(R.id.login_error)
        val linkCreate = findViewById<TextView>(R.id.link_create_business)
        val linkForgot = findViewById<TextView>(R.id.link_forgot_password)

        loginTitle.setText(R.string.pos_login)
        username.setText(prefs.getString("last_login_identifier", prefs.getString("username", "")) ?: "")

        fun apiBase() = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: BuildConfig.DEFAULT_API_BASE_URL

        linkCreate.setOnClickListener {
            loginCard.isVisible = false
            registerCard.isVisible = true
            loginTitle.setText(R.string.register_business_title)
        }

        findViewById<TextView>(R.id.link_back_to_login).setOnClickListener {
            registerCard.isVisible = false
            loginCard.isVisible = true
            loginTitle.setText(R.string.pos_login)
        }

        linkForgot.setOnClickListener {
            api = SyncWorker.createApi(apiBase())
            api?.let { showForgotPasswordFlow(it) }
        }

        loginButton.setOnClickListener {
            val user = username.text.toString().trim()
            val pass = password.text.toString()
            if (user.isBlank() || pass.isBlank()) {
                loginError.text = getString(R.string.login_error)
                loginError.visibility = View.VISIBLE
                return@setOnClickListener
            }
            loginError.visibility = View.GONE
            api = SyncWorker.createApi(apiBase())
            val session = SessionStore(this)
            lifecycleScope.launch {
                try {
                    if (user.contains('@')) {
                        val res = api!!.authLogin(LoginEmailRequest(email = user, password = pass))
                        if (!res.isSuccessful) {
                            runOnUiThread {
                                loginError.text = httpErrorDetail(res) ?: getString(R.string.login_error)
                                loginError.visibility = View.VISIBLE
                            }
                            return@launch
                        }
                        val dto = res.body()!!
                        applySaasAuthDto(session, prefs, dto)
                    } else {
                        val res = api!!.login(user, pass)
                        if (!res.isSuccessful) {
                            runOnUiThread {
                                loginError.text = getString(R.string.login_error)
                                loginError.visibility = View.VISIBLE
                            }
                            return@launch
                        }
                        val data = res.body()!!
                        session.saveSession(
                            accessToken = data.access_token,
                            refreshToken = "",
                            userId = 0,
                            tenantId = null,
                            tenantUid = null,
                            username = data.username ?: user,
                            role = data.role ?: "cashier",
                            subscriptionStatus = "active",
                            lastVerifiedAtMs = System.currentTimeMillis(),
                        )
                        prefs.edit().putString("last_login_identifier", user).apply()
                    }
                    loadProductsIntoDb(session.getAccessToken()!!)
                    runOnUiThread {
                        loginContainer.isVisible = false
                        posContainer.isVisible = true
                        refreshSessionInBackground(prefs)
                        setupPos(posContainer, prefs)
                    }
                } catch (e: Exception) {
                    val isOffline = isOfflineException(e)
                    if (isOffline && canOpenOfflineMode(prefs)) {
                        runOnUiThread {
                            loginError.visibility = View.GONE
                            Toast.makeText(
                                this@MainActivity,
                                getString(R.string.offline_mode_ready) + ". " + getString(R.string.sync_when_online),
                                Toast.LENGTH_LONG
                            ).show()
                            loginContainer.isVisible = false
                            posContainer.isVisible = true
                            refreshSessionInBackground(prefs)
                            setupPos(posContainer, prefs)
                        }
                    } else {
                        val msg = if (isOffline) {
                            if (hasCachedOfflineData()) getString(R.string.offline_sign_in)
                            else getString(R.string.offline_mode_unavailable)
                        } else {
                            getString(R.string.login_error) + " " + (e.message ?: "")
                        }
                        runOnUiThread {
                            loginError.text = msg
                            loginError.visibility = View.VISIBLE
                        }
                    }
                }
            }
        }

        setupRegisterPanel(prefs, loginContainer, posContainer, loginCard, registerCard, loginTitle)

        val cmLogin = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val loginHasNet = cmLogin.activeNetwork?.let { net ->
            cmLogin.getNetworkCapabilities(net)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        } ?: false
        registerConnectivitySyncWatcher(prefs, null)
        if (loginHasNet) {
            triggerSyncWhenOnline()
            refreshSessionInBackground(prefs)
        }
    }

    private fun setupRegisterPanel(
        prefs: android.content.SharedPreferences,
        loginContainer: View,
        posContainer: View,
        loginCard: View,
        registerCard: View,
        loginTitle: TextView,
    ) {
        val bName = findViewById<EditText>(R.id.reg_business_name)
        val oName = findViewById<EditText>(R.id.reg_owner_name)
        val phone = findViewById<EditText>(R.id.reg_phone)
        val email = findViewById<EditText>(R.id.reg_email)
        val pass = findViewById<EditText>(R.id.reg_password)
        val btn = findViewById<android.widget.Button>(R.id.register_button)
        val regErr = findViewById<TextView>(R.id.register_error)
        btn.setOnClickListener {
            val req = RegisterRequest(
                business_name = bName.text.toString().trim(),
                owner_name = oName.text.toString().trim(),
                phone = phone.text.toString().trim(),
                email = email.text.toString().trim(),
                password = pass.text.toString(),
            )
            if (req.business_name.length < 2 || req.owner_name.length < 2 || req.phone.length < 6 ||
                !req.email.contains('@')
            ) {
                regErr.text = getString(R.string.register_error)
                regErr.visibility = View.VISIBLE
                return@setOnClickListener
            }
            if (!meetsSaaSRegisterPasswordRules(req.password)) {
                regErr.text = getString(R.string.password_requirements)
                regErr.visibility = View.VISIBLE
                return@setOnClickListener
            }
            regErr.visibility = View.GONE
            val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: BuildConfig.DEFAULT_API_BASE_URL
            api = SyncWorker.createApi(baseUrl)
            val session = SessionStore(this)
            lifecycleScope.launch {
                try {
                    val res = api!!.authRegister(req)
                    if (!res.isSuccessful) {
                        runOnUiThread {
                            regErr.text = httpErrorDetail(res) ?: getString(R.string.register_error)
                            regErr.visibility = View.VISIBLE
                        }
                        return@launch
                    }
                    val dto = res.body()!!
                    applySaasAuthDto(session, prefs, dto)
                    loadProductsIntoDb(dto.access_token)
                    runOnUiThread {
                        registerCard.isVisible = false
                        loginCard.isVisible = true
                        loginTitle.setText(R.string.pos_login)
                        loginContainer.isVisible = false
                        posContainer.isVisible = true
                        refreshSessionInBackground(prefs)
                        setupPos(posContainer, prefs)
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        regErr.text = if (isOfflineException(e)) {
                            getString(R.string.register_requires_network)
                        } else {
                            e.message ?: getString(R.string.register_error)
                        }
                        regErr.visibility = View.VISIBLE
                    }
                }
            }
        }
    }

    private fun showForgotPasswordFlow(api: ApiService) {
        val pad = (resources.displayMetrics.density * 16).toInt()
        val emailEt = EditText(this).apply {
            hint = getString(R.string.email)
            inputType = InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS
            setPadding(pad, pad, pad, 0)
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.forgot_password_title)
            .setView(emailEt)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.forgot_send, null)
            .setNeutralButton(R.string.reset_with_token, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val em = emailEt.text.toString().trim()
                if (em.isBlank()) return@setOnClickListener
                lifecycleScope.launch {
                    try {
                        val res = api.authForgotPassword(ForgotPasswordRequest(em))
                        val msg = res.body()?.message
                        runOnUiThread {
                            Toast.makeText(
                                this@MainActivity,
                                msg ?: getString(R.string.forgot_send),
                                Toast.LENGTH_LONG
                            ).show()
                            dialog.dismiss()
                        }
                    } catch (ex: Exception) {
                        runOnUiThread {
                            Toast.makeText(this@MainActivity, ex.message ?: "", Toast.LENGTH_LONG).show()
                        }
                    }
                }
            }
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                dialog.dismiss()
                showResetWithTokenDialog(api)
            }
        }
        dialog.show()
    }

    private fun showResetWithTokenDialog(api: ApiService) {
        val pad = (resources.displayMetrics.density * 16).toInt()
        val wrap = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
        }
        val tokenEt = EditText(this).apply { hint = getString(R.string.reset_token_hint); setSingleLine() }
        val newPassEt = EditText(this).apply {
            hint = getString(R.string.new_password)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        wrap.addView(tokenEt)
        wrap.addView(newPassEt)
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.reset_with_token)
            .setView(wrap)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(android.R.string.ok, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val tok = tokenEt.text.toString().trim()
                val np = newPassEt.text.toString()
                if (tok.length < 10 || np.length < 8) return@setOnClickListener
                lifecycleScope.launch {
                    try {
                        val res = api.authResetPassword(ResetPasswordRequest(token = tok, new_password = np))
                        runOnUiThread {
                            if (res.isSuccessful) {
                                Toast.makeText(
                                    this@MainActivity,
                                    getString(android.R.string.ok),
                                    Toast.LENGTH_SHORT
                                ).show()
                                dialog.dismiss()
                            } else {
                                Toast.makeText(
                                    this@MainActivity,
                                    httpErrorDetail(res) ?: "",
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                        }
                    } catch (ex: Exception) {
                        runOnUiThread {
                            Toast.makeText(this@MainActivity, ex.message ?: "", Toast.LENGTH_LONG).show()
                        }
                    }
                }
            }
        }
        dialog.show()
    }

    private fun httpErrorDetail(res: Response<*>): String? {
        val raw = try {
            res.errorBody()?.string()
        } catch (_: Exception) {
            null
        } ?: return null
        try {
            val root = JSONObject(raw)
            when (val detail = root.opt("detail")) {
                is String -> if (detail.isNotBlank()) return detail
                is JSONArray -> {
                    if (detail.length() > 0) {
                        val msg = detail.optJSONObject(0)?.optString("msg")?.trim()
                        if (!msg.isNullOrBlank()) {
                            return msg.removePrefix("Value error, ").trim()
                        }
                    }
                }
            }
        } catch (_: Exception) {}
        val m = Regex(""""detail"\s*:\s*"([^"]+)"""").find(raw)
        if (m != null) return m.groupValues[1]
        return raw.take(350)
    }

    /** Mirrors [RegisterBody.password_strength] in app/saas_auth_routes.py */
    private fun meetsSaaSRegisterPasswordRules(password: String): Boolean {
        if (password.length < 8 || password.length > 128) return false
        val hasLetter = password.any { it in 'a'..'z' || it in 'A'..'Z' }
        val hasDigit = password.any { it.isDigit() }
        return hasLetter && hasDigit
    }

    private fun applySaasAuthDto(session: SessionStore, prefs: android.content.SharedPreferences, dto: AuthResponseDto) {
        val lastMs = parseIsoToMs(dto.last_verified_at) ?: System.currentTimeMillis()
        session.saveSession(
            accessToken = dto.access_token,
            refreshToken = dto.refresh_token,
            userId = dto.user_id,
            tenantId = dto.tenant_id,
            tenantUid = dto.tenant_uid,
            username = dto.username,
            role = dto.role,
            subscriptionStatus = dto.subscription_status,
            lastVerifiedAtMs = lastMs,
        )
        prefs.edit().putString("last_login_identifier", dto.username).apply()
    }

    private fun parseIsoToMs(iso: String?): Long? {
        if (iso.isNullOrBlank()) return null
        return try {
            val trimmed = iso.removeSuffix("Z")
            val core = trimmed.substringBefore('.').replace(' ', 'T').trim()
            val fmt = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).apply {
                timeZone = java.util.TimeZone.getTimeZone("UTC")
            }
            fmt.parse(core)?.time
        } catch (_: Exception) {
            null
        }
    }

    private fun isOfflineException(e: Throwable): Boolean {
        var t: Throwable? = e
        while (t != null) {
            if (t is UnknownHostException || t is ConnectException || t is SocketTimeoutException) return true
            val msg = t.message
            if (msg?.contains("Unable to resolve host", ignoreCase = true) == true) return true
            if (msg?.contains("Failed to connect", ignoreCase = true) == true) return true
            if (msg?.contains("Network is unreachable", ignoreCase = true) == true) return true
            t = t.cause
        }
        return false
    }

    private fun refreshSessionInBackground(prefs: android.content.SharedPreferences) {
        lifecycleScope.launch(Dispatchers.IO) {
            val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: return@launch
            val svc = try {
                SyncWorker.createApi(baseUrl)
            } catch (_: Exception) {
                return@launch
            }
            val session = SessionStore(this@MainActivity)
            val token = session.getAccessToken() ?: return@launch
            try {
                val verify = svc.authVerify("Bearer $token")
                if (verify.isSuccessful && verify.body()?.valid == true) {
                    val b = verify.body()!!
                    val sub = b.subscription_status ?: "active"
                    val verifiedMs = parseIsoToMs(b.last_verified_at) ?: System.currentTimeMillis()
                    session.updateSubscriptionMeta(sub, verifiedMs)
                    return@launch
                }
                val refreshTok = session.getRefreshToken()
                if (!refreshTok.isNullOrBlank()) {
                    val r = svc.authRefresh(RefreshRequest(refreshTok))
                    if (r.isSuccessful && r.body() != null) {
                        val a = r.body()!!
                        session.updateTokens(a.access_token, a.refresh_token)
                        applySaasAuthDto(session, prefs, a)
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    private suspend fun canOpenOfflineMode(prefs: android.content.SharedPreferences): Boolean {
        val session = SessionStore(this@MainActivity)
        val token = prefs.getString("token", null)
        if (token.isNullOrBlank()) return false
        if (!session.canUseOffline()) return false
        return hasCachedOfflineData()
    }

    private suspend fun hasCachedOfflineData(): Boolean {
        return AppDatabase.getInstance(this@MainActivity).productDao().countActive() > 0
    }

    private suspend fun loadProductsIntoDb(token: String) {
        val apiService = api ?: return
        withContext(Dispatchers.IO) {
            try {
                val res = apiService.getProducts("Bearer $token")
                if (res.isSuccessful) {
                    val list = res.body() ?: emptyList()
                    val db = AppDatabase.getInstance(this@MainActivity)
                    val entities = list.map { dto ->
                        com.pos.mobile.data.local.entity.ProductEntity(
                            id = dto.id,
                            name = dto.name,
                            barcode = dto.barcode,
                            categoryId = dto.category_id,
                            stockQty = dto.stock_qty,
                            sellingPrice = dto.selling_price,
                            costPrice = dto.cost_price,
                            isActive = dto.is_active,
                            serverSyncedAt = System.currentTimeMillis()
                        )
                    }
                    db.productDao().deleteAll()
                    db.productDao().insertAll(entities)
                }
            } catch (_: Exception) {}
        }
    }

    private var networkCallback: NetworkCallback? = null

    private fun unregisterConnectivitySyncWatcher() {
        val cb = networkCallback ?: return
        try {
            (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).unregisterNetworkCallback(cb)
        } catch (_: Exception) {}
        networkCallback = null
    }

    /**
     * When internet becomes available: refresh session, enqueue sync. Used on login screen and POS.
     */
    private fun registerConnectivitySyncWatcher(
        prefs: android.content.SharedPreferences,
        onAvailabilityChange: ((Boolean) -> Unit)?,
    ) {
        unregisterConnectivitySyncWatcher()
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        networkCallback = object : NetworkCallback() {
            override fun onAvailable(network: Network) {
                onAvailabilityChange?.invoke(true)
                triggerSyncWhenOnline()
                refreshSessionInBackground(prefs)
            }
            override fun onLost(network: Network) {
                val stillHas = cm.activeNetwork?.let {
                    cm.getNetworkCapabilities(it)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
                } ?: false
                onAvailabilityChange?.invoke(stillHas)
            }
        }
        val request = NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build()
        cm.registerNetworkCallback(request, networkCallback!!)
    }

    private fun setupPos(posContainer: View, prefs: android.content.SharedPreferences) {
        val shopName = posContainer.findViewById<android.widget.TextView>(R.id.shop_name)
        shopName.text = prefs.getString("store_name", getString(R.string.store_name)) ?: getString(R.string.store_name)

        // Offline indicator: show "Offline" when no network; UI is always available from local data
        val statusIndicator = posContainer.findViewById<android.widget.TextView>(R.id.status_offline_indicator)
        fun updateOfflineIndicator(connected: Boolean) {
            statusIndicator.isVisible = !connected
            statusIndicator.text = getString(R.string.status_offline)
        }
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val hasNetwork = cm.activeNetwork?.let { net ->
            cm.getNetworkCapabilities(net)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        } ?: false
        updateOfflineIndicator(hasNetwork)
        registerConnectivitySyncWatcher(prefs) { connected -> updateOfflineIndicator(connected) }

        // Sync only when online; enqueue one-time sync so data refreshes in background (UI never waits)
        triggerSyncWhenOnline()

        val barcodeInput = posContainer.findViewById<android.widget.EditText>(R.id.barcode_input)
        val searchResults = posContainer.findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.search_results)
        val cartList = posContainer.findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.cart_list)
        val btnPayment = posContainer.findViewById<android.widget.Button>(R.id.btn_payment)
        val btnMorePages = posContainer.findViewById<android.widget.Button>(R.id.btn_more_pages)
        val btnLayby = posContainer.findViewById<android.widget.Button>(R.id.btn_layby)
        val btnLogout = posContainer.findViewById<android.widget.Button>(R.id.btn_logout)
        val iconMore = posContainer.findViewById<android.widget.Button>(R.id.icon_more)
        val iconPayment = posContainer.findViewById<android.widget.Button>(R.id.icon_payment)
        val iconTheme = posContainer.findViewById<android.widget.Button>(R.id.icon_theme)
        val iconSettings = posContainer.findViewById<android.widget.Button>(R.id.icon_settings)
        val iconWithdraw = posContainer.findViewById<android.widget.Button>(R.id.icon_withdraw)

        searchAdapter = SearchProductAdapter { product ->
            viewModel.addToCart(product, 1)
            barcodeInput.text.clear()
            searchResults.isVisible = false
            searchAdapter.submitList(emptyList())
        }
        searchResults.layoutManager = LinearLayoutManager(this)
        searchResults.adapter = searchAdapter
        searchResults.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
        searchResults.itemAnimator = null

        cartAdapter = CartAdapter(
            onQtyChange = { index, qty -> viewModel.updateQty(index, qty) },
            onDiscChange = { index, disc -> viewModel.updateDiscount(index, disc) },
            onRemove = { index -> viewModel.removeFromCart(index) }
        )
        cartList.layoutManager = LinearLayoutManager(this)
        cartList.adapter = cartAdapter
        cartList.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
        cartList.itemAnimator = null
        cartList.setHasFixedSize(false)

        lifecycleScope.launch {
            viewModel.cart.collect { list ->
                cartAdapter.submitList(list.toList())
            }
        }

        barcodeInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE || actionId == EditorInfo.IME_ACTION_GO) {
                val value = barcodeInput.text.toString().trim()
                if (value.isNotEmpty()) {
                    val product = viewModel.findProductByBarcode(value)
                    if (product != null) {
                        viewModel.addToCart(product, 1)
                        barcodeInput.text.clear()
                        searchResults.isVisible = false
                    } else {
                        val matches = viewModel.searchProducts(value)
                        if (matches.size == 1) {
                            viewModel.addToCart(matches[0], 1)
                            barcodeInput.text.clear()
                            searchResults.isVisible = false
                        } else if (matches.isNotEmpty()) {
                            searchAdapter.submitList(matches.take(20))
                            searchResults.isVisible = true
                        } else {
                            Toast.makeText(this, "No product found", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
                true
            } else false
        }

        btnPayment.setOnClickListener { showPaymentSheet() }

        fun openMorePages(anchor: View) {
            val popup = PopupMenu(this, anchor)
            popup.menuInflater.inflate(R.menu.pos_pages_menu, popup.menu)
            popup.setOnMenuItemClickListener { item ->
                if (item.itemId == R.id.page_store) {
                    // Already on Store; just dismiss popup
                    return@setOnMenuItemClickListener true
                }
                val (path, title) = when (item.itemId) {
                    R.id.page_admin -> "/admin" to "Admin"
                    R.id.page_layby -> "/layby" to "Layby"
                    R.id.page_pending_collection -> "/pending-collection" to "Pending Collection"
                    R.id.page_store_settings -> "/store-settings" to "Store Settings"
                    R.id.page_analytics -> "/analytics" to "Analytics"
                    R.id.page_accounting -> "/accounting" to "Accounting"
                    R.id.page_withdrawals -> "/withdrawals/history" to "Withdrawals History"
                    R.id.page_outstanding_debts -> "/debts/outstanding" to "Outstanding Debts"
                    else -> return@setOnMenuItemClickListener false
                }
                startActivity(Intent(this, WebViewActivity::class.java).apply {
                    putExtra(WebViewActivity.EXTRA_PATH, path)
                    putExtra(WebViewActivity.EXTRA_TITLE, title)
                })
                true
            }
            popup.show()
        }
        btnMorePages.setOnClickListener { v -> openMorePages(v) }
        iconMore.setOnClickListener { v -> openMorePages(v) }
        iconPayment.setOnClickListener { showPaymentSheet() }
        iconTheme.setOnClickListener { showThemeDialog(prefs) }
        iconSettings.setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/store-settings")
                putExtra(WebViewActivity.EXTRA_TITLE, "Store Settings")
            })
        }
        iconWithdraw.setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/withdrawals/history")
                putExtra(WebViewActivity.EXTRA_TITLE, "Withdrawals History")
            })
        }
        btnLayby.setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/layby")
                putExtra(WebViewActivity.EXTRA_TITLE, "Layby")
            })
        }
        btnLogout.setOnClickListener {
            lifecycleScope.launch(Dispatchers.IO) {
                val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: ""
                val session = SessionStore(this@MainActivity)
                val refresh = session.getRefreshToken()
                try {
                    if (!refresh.isNullOrBlank()) {
                        val svc = SyncWorker.createApi(baseUrl)
                        svc.authLogout(LogoutRequest(refresh))
                    }
                } catch (_: Exception) {
                }
                session.clear()
                prefs.edit()
                    .remove("token")
                    .remove("username")
                    .remove("role")
                    .remove("last_login_identifier")
                    .apply()
                runOnUiThread { recreate() }
            }
        }
    }

    private fun showPaymentSheet() {
        val sheetView = LayoutInflater.from(this).inflate(R.layout.bottom_sheet_payment, null)
        val dialog = BottomSheetDialog(this)
        dialog.setContentView(sheetView)

        val subtotalTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_subtotal)
        val discountTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_discount)
        val totalTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_total)
        val customerEt = sheetView.findViewById<android.widget.EditText>(R.id.payment_customer)
        val payCash = sheetView.findViewById<android.widget.EditText>(R.id.pay_cash)
        val payMobile = sheetView.findViewById<android.widget.EditText>(R.id.pay_mobile)
        val payCard = sheetView.findViewById<android.widget.EditText>(R.id.pay_card)
        val payCredit = sheetView.findViewById<android.widget.EditText>(R.id.pay_credit)
        val collectionSpinner = sheetView.findViewById<android.widget.Spinner>(R.id.collection_status)
        val btnComplete = sheetView.findViewById<android.widget.Button>(R.id.btn_complete_sale)
        val messageTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_message)

        val format = java.text.NumberFormat.getCurrencyInstance(java.util.Locale.US)
        subtotalTv.text = format.format(viewModel.subtotal)
        discountTv.text = format.format(viewModel.discountTotal)
        totalTv.text = format.format(viewModel.total)

        val statusAdapter = ArrayAdapter.createFromResource(
            this,
            R.array.collection_status_options,
            android.R.layout.simple_spinner_item
        ).apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
        collectionSpinner.adapter = statusAdapter

        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        var receiptCart: List<CartLine>? = null
        var receiptPayments: List<Pair<String, Double>> = emptyList()
        var receiptCustomer: String? = null
        var receiptStatus = "collected"
        var receiptSubtotal = 0.0
        var receiptDiscount = 0.0
        var receiptTotal = 0.0

        viewModel.clearSaleMessage()
        lifecycleScope.launch {
            viewModel.saleCompleteMessage.collect { msg ->
                if (msg != null) {
                    messageTv.text = msg
                    messageTv.visibility = View.VISIBLE
                    viewModel.clearSaleMessage()
                    if (msg.startsWith("Sale saved")) {
                        val cart = receiptCart
                        if (cart != null) {
                            val storeName = prefs.getString("store_name", getString(R.string.store_name))
                                ?: getString(R.string.store_name)
                            val cashier = prefs.getString("username", null)
                            ReceiptPrinter.printSale(
                                context = this@MainActivity,
                                storeName = storeName,
                                cartLines = cart,
                                subtotal = receiptSubtotal,
                                discountTotal = receiptDiscount,
                                total = receiptTotal,
                                payments = receiptPayments,
                                customerName = receiptCustomer,
                                collectionStatus = receiptStatus,
                                cashierName = cashier,
                            )
                        }
                        receiptCart = null
                        triggerSyncWhenOnline()
                        dialog.dismiss()
                    }
                }
            }
        }
        btnComplete.setOnClickListener {
            val cash = payCash.text.toString().toDoubleOrNull() ?: 0.0
            val mobile = payMobile.text.toString().toDoubleOrNull() ?: 0.0
            val card = payCard.text.toString().toDoubleOrNull() ?: 0.0
            val credit = payCredit.text.toString().toDoubleOrNull() ?: 0.0
            val status = if (collectionSpinner.selectedItemPosition == 1) "to_collect" else "collected"
            receiptCart = viewModel.cart.value.toList()
            receiptSubtotal = viewModel.subtotal
            receiptDiscount = viewModel.discountTotal
            receiptTotal = viewModel.total
            receiptCustomer = customerEt.text.toString().trim().takeIf { it.isNotBlank() }
            receiptStatus = status
            receiptPayments = buildList {
                if (cash > 0) add("cash" to cash)
                if (mobile > 0) add("mobile_money" to mobile)
                if (card > 0) add("card" to card)
                if (credit > 0) add("credit" to credit)
            }
            viewModel.completeSale(
                customerName = receiptCustomer,
                cash = cash,
                mobile = mobile,
                card = card,
                credit = credit,
                collectionStatus = status,
                notes = null
            )
        }
        dialog.show()
    }

    private fun applyThemeToRoot(prefs: android.content.SharedPreferences) {
        val root = findViewById<View>(R.id.root_container) ?: return
        val theme = prefs.getString("theme", "default") ?: "default"
        when (theme) {
            "light" -> root.setBackgroundResource(R.drawable.bg_theme_light)
            "classic" -> root.setBackgroundColor(Color.parseColor("#e8e8e8"))
            else -> root.setBackgroundResource(R.drawable.bg_gradient)
        }
    }

    private fun showThemeDialog(prefs: android.content.SharedPreferences) {
        val options = arrayOf(
            getString(R.string.theme_default),
            getString(R.string.theme_light),
            getString(R.string.theme_classic)
        )
        val values = arrayOf("default", "light", "classic")
        val current = prefs.getString("theme", "default") ?: "default"
        val index = values.indexOf(current).coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle(R.string.theme_dialog_title)
            .setSingleChoiceItems(options, index) { dialog, which ->
                val theme = values[which]
                prefs.edit().putString("theme", theme).apply()
                applyThemeToRoot(prefs)
                dialog.dismiss()
                Toast.makeText(this, getString(R.string.theme) + ": " + options[which], Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    /** Enqueue a one-time sync when online. UI never waits; sync runs in background. */
    private fun triggerSyncWhenOnline() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .addTag("pos_sync_on_action")
            .build()
        WorkManager.getInstance(this).enqueue(work)
    }

    override fun onDestroy() {
        unregisterConnectivitySyncWatcher()
        super.onDestroy()
    }
}

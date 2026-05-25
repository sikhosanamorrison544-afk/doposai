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
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
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
import com.pos.mobile.data.local.entity.SyncQueueEntity
import com.pos.mobile.data.sync.SyncRepository
import com.pos.mobile.data.sync.SyncWorker
import com.pos.mobile.sync.NetworkUtils
import com.pos.mobile.printer.BluetoothPermissionDelegate
import com.pos.mobile.printer.PrinterPermissionHelper
import com.pos.mobile.printer.PrinterSetupDialog
import com.pos.mobile.printer.bluetoothPermissionDelegate
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
    private var posSearchSetupDone = false
    private var posUiSetupDone = false
    private var saleEventsObserving = false
    private var activePaymentDialog: BottomSheetDialog? = null
    private var manualSyncInProgress = false
    private var api: ApiService? = null
    private var posContainerRef: View? = null
    private var notificationBadgeJob: kotlinx.coroutines.Job? = null

    companion object {
        private const val REQ_NOTIFICATIONS = 2001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BluetoothPermissionDelegate.install(this)
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
            val offlineOk = session.canUseOfflineForPos() && tokenPresent && cachedProducts
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

        val serverUrlInput = findViewById<EditText>(R.id.login_server_url)
        serverUrlInput.setText(
            prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: BuildConfig.DEFAULT_API_BASE_URL,
        )

        fun apiBase(): String {
            val raw = serverUrlInput.text.toString().trim()
            val url = if (raw.isBlank()) BuildConfig.DEFAULT_API_BASE_URL else raw
            return if (url.endsWith("/")) url else "$url/"
        }

        fun persistServerUrl() {
            prefs.edit().putString("base_url", apiBase()).apply()
        }

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
            persistServerUrl()
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
                    val token = session.getAccessToken()!!
                    val synced = syncEssentialData(token)
                    val (productCount, cacheCount) = withContext(Dispatchers.IO) {
                        val db = AppDatabase.getInstance(this@MainActivity)
                        db.productDao().countActive() to db.apiCacheDao().count()
                    }
                    withContext(Dispatchers.Main) {
                        showSyncResultToast(synced, productCount, cacheCount)
                        loginContainer.isVisible = false
                        posContainer.isVisible = true
                        refreshSessionInBackground(prefs)
                        setupPos(posContainer, prefs)
                    }
                    promptTrialSubscriptionAfterAuth()
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
            val serverUrlInput = findViewById<EditText>(R.id.login_server_url)
            val raw = serverUrlInput.text.toString().trim()
            val baseUrl = (if (raw.isBlank()) BuildConfig.DEFAULT_API_BASE_URL else raw).let {
                if (it.endsWith("/")) it else "$it/"
            }
            prefs.edit().putString("base_url", baseUrl).apply()
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
                    val synced = syncEssentialData(dto.access_token)
                    val (productCount, cacheCount) = withContext(Dispatchers.IO) {
                        val db = AppDatabase.getInstance(this@MainActivity)
                        db.productDao().countActive() to db.apiCacheDao().count()
                    }
                    withContext(Dispatchers.Main) {
                        showSyncResultToast(synced, productCount, cacheCount)
                        registerCard.isVisible = false
                        loginCard.isVisible = true
                        loginTitle.setText(R.string.pos_login)
                        loginContainer.isVisible = false
                        posContainer.isVisible = true
                        refreshSessionInBackground(prefs)
                        setupPos(posContainer, prefs)
                    }
                    promptTrialSubscriptionAfterAuth()
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
            var token = session.getAccessToken() ?: return@launch
            try {
                val verify = svc.authVerify("Bearer $token")
                if (verify.isSuccessful && verify.body()?.valid == true) {
                    val b = verify.body()!!
                    val sub = b.subscription_status ?: "active"
                    val verifiedMs = parseIsoToMs(b.last_verified_at) ?: System.currentTimeMillis()
                    session.updateSubscriptionMeta(sub, verifiedMs)
                    syncEssentialData(token)
                    return@launch
                }
                val refreshTok = session.getRefreshToken()
                if (!refreshTok.isNullOrBlank()) {
                    val r = svc.authRefresh(RefreshRequest(refreshTok))
                    if (r.isSuccessful && r.body() != null) {
                        val a = r.body()!!
                        session.updateTokens(a.access_token, a.refresh_token)
                        applySaasAuthDto(session, prefs, a)
                        token = a.access_token
                    }
                }
                syncEssentialData(token)
            } catch (e: Exception) {
                Log.w("MainActivity", "Session refresh failed", e)
            }
        }
    }

    private suspend fun canOpenOfflineMode(prefs: android.content.SharedPreferences): Boolean {
        val session = SessionStore(this@MainActivity)
        val token = prefs.getString("token", null)
        if (token.isNullOrBlank()) return false
        if (!session.canUseOfflineForPos()) return false
        return hasCachedOfflineData()
    }

    private suspend fun hasCachedOfflineData(): Boolean {
        val db = AppDatabase.getInstance(this@MainActivity)
        return db.productDao().countActive() > 0 || db.apiCacheDao().count() > 0
    }

    private fun createSyncRepository(readTimeoutSec: Long = 25): SyncRepository {
        val db = AppDatabase.getInstance(this)
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: BuildConfig.DEFAULT_API_BASE_URL
        val api = SyncWorker.createApi(baseUrl, readTimeoutSec)
        return SyncWorker.createRepository(this, baseUrl, api, db)
    }

    /** Pull master DB snapshot (products, reports, debts, pages) for offline use. */
    private suspend fun syncEssentialData(token: String): Boolean = withContext(Dispatchers.IO) {
        try {
            val ok = createSyncRepository().syncMasterDatabase(this@MainActivity, token).isSuccess
            if (ok) {
                SessionStore(this@MainActivity).recordOfflineAnchor()
            }
            ok
        } catch (e: Exception) {
            Log.e("MainActivity", "Master data sync failed", e)
            false
        }
    }

    private fun showSyncResultToast(synced: Boolean, productCount: Int, cacheCount: Int = 0) {
        when {
            synced && productCount > 0 -> Toast.makeText(
                this,
                if (cacheCount > 0) {
                    getString(R.string.synced_master, productCount, cacheCount)
                } else {
                    getString(R.string.synced_products, productCount)
                },
                Toast.LENGTH_SHORT
            ).show()
            productCount == 0 && !synced -> Toast.makeText(
                this,
                getString(R.string.sync_failed_no_products),
                Toast.LENGTH_LONG
            ).show()
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

    private var posPrefs: android.content.SharedPreferences? = null

    override fun onResume() {
        super.onResume()
        val posContainer = findViewById<View>(R.id.pos_container) ?: return
        if (!posContainer.isVisible) return
        val prefs = posPrefs ?: getSharedPreferences("pos", MODE_PRIVATE)
        refreshNativeShopName(posContainer, prefs)
        val token = SessionStore(this).getAccessToken() ?: prefs.getString("token", null)
        if (!token.isNullOrBlank() && NetworkUtils.isOnline(this)) {
            lifecycleScope.launch(Dispatchers.IO) {
                try {
                    createSyncRepository().persistStoreSettings(this@MainActivity, token)
                } catch (_: Exception) { /* ignore */ }
                withContext(Dispatchers.Main) {
                    refreshNativeShopName(posContainer, prefs)
                }
            }
        }
        findViewById<android.widget.Button>(R.id.icon_notifications)?.let { refreshNotificationBadge(it) }
        refreshSubscriptionWarning(posContainer)
        refreshSubscriptionFromServer()
    }

    private fun refreshNativeShopName(posContainer: View, prefs: android.content.SharedPreferences) {
        val shopName = posContainer.findViewById<android.widget.TextView>(R.id.shop_name) ?: return
        val username = prefs.getString("username", "") ?: ""
        val role = prefs.getString("role", "cashier") ?: "cashier"
        val storeLabel = prefs.getString("store_name", getString(R.string.store_name)) ?: getString(R.string.store_name)
        shopName.text = if (username.isNotBlank()) "$storeLabel — $username ($role)" else storeLabel
    }

    private fun setupPos(posContainer: View, prefs: android.content.SharedPreferences) {
        posPrefs = prefs
        refreshNativeShopName(posContainer, prefs)
        if (posUiSetupDone) return
        posUiSetupDone = true

        val role = PosAuth.role(this)

        val posMessageTv = posContainer.findViewById<TextView>(R.id.pos_message)
        lifecycleScope.launch {
            viewModel.posMessage.collect { msg ->
                if (msg.isNullOrBlank()) {
                    posMessageTv.visibility = View.GONE
                } else {
                    posMessageTv.text = msg
                    posMessageTv.visibility = View.VISIBLE
                }
            }
        }

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
        val btnAdmin = posContainer.findViewById<android.widget.Button>(R.id.btn_admin)
        val btnLayby = posContainer.findViewById<android.widget.Button>(R.id.btn_layby)
        val btnLogout = posContainer.findViewById<android.widget.Button>(R.id.btn_logout)
        val iconSync = posContainer.findViewById<android.widget.Button>(R.id.icon_sync)
        val iconPayment = posContainer.findViewById<android.widget.Button>(R.id.icon_payment)
        val iconTheme = posContainer.findViewById<android.widget.Button>(R.id.icon_theme)
        val iconPrinter = posContainer.findViewById<android.widget.Button>(R.id.icon_printer)
        val iconSettings = posContainer.findViewById<android.widget.Button>(R.id.icon_settings)
        val iconWithdraw = posContainer.findViewById<android.widget.Button>(R.id.icon_withdraw)
        val iconNotifications = posContainer.findViewById<android.widget.Button>(R.id.icon_notifications)
        val iconStats = posContainer.findViewById<android.widget.Button>(R.id.icon_stats)
        val iconBilling = posContainer.findViewById<android.widget.Button>(R.id.icon_billing)
        posContainerRef = posContainer

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

        val cartSubtotalTv = posContainer.findViewById<TextView>(R.id.cart_subtotal)
        val cartDiscountTv = posContainer.findViewById<TextView>(R.id.cart_discount)
        val cartGrandTotalTv = posContainer.findViewById<TextView>(R.id.cart_grand_total)
        val cartFormat = java.text.NumberFormat.getCurrencyInstance(java.util.Locale.US)

        lifecycleScope.launch {
            viewModel.cart.collect { list ->
                cartAdapter.submitList(list.toList())
            }
        }
        lifecycleScope.launch {
            viewModel.cartTotals.collect { totals ->
                cartSubtotalTv.text = cartFormat.format(totals.subtotal)
                cartDiscountTv.text = cartFormat.format(totals.discountTotal)
                cartGrandTotalTv.text = cartFormat.format(totals.total)
            }
        }

        if (!saleEventsObserving) {
            saleEventsObserving = true
            lifecycleScope.launch {
                viewModel.saleEvents.collect { event ->
                    when (event) {
                        is SaleUiEvent.Success -> {
                            activePaymentDialog?.dismiss()
                            activePaymentDialog = null
                            Toast.makeText(this@MainActivity, event.message, Toast.LENGTH_LONG).show()
                            triggerSyncWhenOnline()
                        }
                        is SaleUiEvent.Failed -> {
                            Toast.makeText(this@MainActivity, event.message, Toast.LENGTH_LONG).show()
                        }
                    }
                }
            }
        }

        fun applySearchResults(matches: List<ProductEntity>) {
            if (matches.size == 1) {
                viewModel.addToCart(matches[0], 1)
                barcodeInput.text.clear()
                searchResults.isVisible = false
                searchAdapter.submitList(emptyList())
            } else if (matches.isNotEmpty()) {
                searchAdapter.submitList(matches.take(20)) {
                    searchResults.isVisible = true
                    searchResults.requestLayout()
                }
            } else {
                searchResults.isVisible = false
                searchAdapter.submitList(emptyList())
            }
        }

        if (!posSearchSetupDone) {
            posSearchSetupDone = true
            barcodeInput.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    val value = s?.toString()?.trim() ?: ""
                    if (value.isEmpty()) {
                        searchResults.isVisible = false
                        searchAdapter.submitList(emptyList())
                        return
                    }
                    lifecycleScope.launch {
                        val matches = viewModel.searchProducts(value)
                        applySearchResults(matches)
                    }
                }
            })
        }

        barcodeInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE || actionId == EditorInfo.IME_ACTION_GO) {
                val value = barcodeInput.text.toString().trim()
                if (value.isNotEmpty()) {
                    lifecycleScope.launch {
                        val product = viewModel.findProductByBarcode(value)
                        if (product != null) {
                            viewModel.addToCart(product, 1)
                            barcodeInput.text.clear()
                            searchResults.isVisible = false
                            searchAdapter.submitList(emptyList())
                        } else {
                            val matches = viewModel.searchProducts(value)
                            if (matches.isEmpty()) {
                                Toast.makeText(this@MainActivity, "No product found", Toast.LENGTH_SHORT).show()
                            } else {
                                applySearchResults(matches)
                            }
                        }
                    }
                }
                true
            } else false
        }

        fun openCheckout() {
            currentFocus?.clearFocus()
            cartAdapter.commitVisibleEdits(cartList)
            if (viewModel.cart.value.isEmpty()) {
                Toast.makeText(this, R.string.cart_empty, Toast.LENGTH_SHORT).show()
                return
            }
            showPaymentSheet()
        }
        btnPayment.setOnClickListener { openCheckout() }

        btnAdmin.isVisible = WebPosRules.roleCanAccessAdmin(role)
        btnAdmin.setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/admin")
                putExtra(WebViewActivity.EXTRA_TITLE, getString(R.string.admin))
            })
        }
        iconSync.setOnClickListener { runManualSync(prefs, iconSync) }
        iconPayment.setOnClickListener { openCheckout() }
        iconTheme.setOnClickListener { showThemeDialog(prefs) }
        iconSettings.setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/store-settings")
                putExtra(WebViewActivity.EXTRA_TITLE, "Store Settings")
            })
        }
        iconPrinter.setOnClickListener {
            try {
                val storeName = prefs.getString("store_name", getString(R.string.store_name))
                    ?: getString(R.string.store_name)
                PrinterSetupDialog.show(this, lifecycleScope, storeName)
            } catch (e: Exception) {
                Log.e("MainActivity", "Printer setup failed", e)
                Toast.makeText(
                    this,
                    getString(R.string.printer_failed, e.message ?: "error"),
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
        iconWithdraw.isVisible = WebPosRules.roleCanAccessWithdrawal(role)
        iconWithdraw.setOnClickListener {
            startActivity(Intent(this, WithdrawalActivity::class.java))
        }
        iconNotifications.setOnClickListener {
            startActivityForResult(
                Intent(this, NotificationsActivity::class.java),
                REQ_NOTIFICATIONS,
            )
        }
        iconStats.setOnClickListener {
            startActivity(Intent(this, StatsActivity::class.java))
        }
        iconBilling.isVisible = WebPosRules.roleCanAccessAdmin(role)
        iconBilling.setOnClickListener {
            startActivity(Intent(this, SubscriptionActivity::class.java))
        }
        refreshNotificationBadge(iconNotifications)
        refreshSubscriptionWarning(posContainer)
        btnLayby.setOnClickListener {
            startActivity(Intent(this, LaybyActivity::class.java))
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
        val posCartList = findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.cart_list)
        if (::cartAdapter.isInitialized && posCartList != null) {
            cartAdapter.commitVisibleEdits(posCartList)
        }
        val sheetView = LayoutInflater.from(this).inflate(R.layout.bottom_sheet_payment, null)
        val dialog = BottomSheetDialog(this)
        dialog.setContentView(sheetView)

        val subtotalTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_subtotal)
        val discountTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_discount)
        val totalTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_total)
        val paidRow = sheetView.findViewById<View>(R.id.payment_paid_row)
        val paidTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_paid)
        val changeRow = sheetView.findViewById<View>(R.id.payment_change_row)
        val changeTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_change)
        val customerEt = sheetView.findViewById<android.widget.EditText>(R.id.payment_customer)
        val payCash = sheetView.findViewById<android.widget.EditText>(R.id.pay_cash)
        val payMobile = sheetView.findViewById<android.widget.EditText>(R.id.pay_mobile)
        val payCard = sheetView.findViewById<android.widget.EditText>(R.id.pay_card)
        val payCredit = sheetView.findViewById<android.widget.EditText>(R.id.pay_credit)
        val collectionSpinner = sheetView.findViewById<android.widget.Spinner>(R.id.collection_status)
        val btnComplete = sheetView.findViewById<android.widget.Button>(R.id.btn_complete_sale)
        val messageTv = sheetView.findViewById<android.widget.TextView>(R.id.payment_message)

        val format = java.text.NumberFormat.getCurrencyInstance(java.util.Locale.US)
        var saleTotal = viewModel.cartTotals.value.total

        fun paymentAmount(et: android.widget.EditText): Double =
            et.text.toString().toDoubleOrNull() ?: 0.0

        fun refreshPaymentTotals() {
            val paid = paymentAmount(payCash) + paymentAmount(payMobile) +
                paymentAmount(payCard) + paymentAmount(payCredit)
            if (paid > 0.005) {
                paidRow.isVisible = true
                paidTv.text = format.format(paid)
            } else {
                paidRow.isVisible = false
            }
            val change = paid - saleTotal
            if (change > 0.005) {
                changeRow.isVisible = true
                changeTv.text = format.format(change)
            } else {
                changeRow.isVisible = false
            }
        }

        fun applyCartTotalsToSheet(totals: CartTotals) {
            saleTotal = totals.total
            subtotalTv.text = format.format(totals.subtotal)
            discountTv.text = format.format(totals.discountTotal)
            totalTv.text = format.format(totals.total)
            refreshPaymentTotals()
        }
        applyCartTotalsToSheet(viewModel.cartTotals.value)
        if (saleTotal > 0.005 && payCash.text.isNullOrBlank()) {
            payCash.setText(String.format(java.util.Locale.US, "%.2f", saleTotal))
            refreshPaymentTotals()
        }

        val totalsJob = lifecycleScope.launch {
            viewModel.cartTotals.collect { totals ->
                if (dialog.isShowing) {
                    applyCartTotalsToSheet(totals)
                }
            }
        }
        activePaymentDialog = dialog

        val paymentWatcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                refreshPaymentTotals()
            }
        }
        payCash.addTextChangedListener(paymentWatcher)
        payMobile.addTextChangedListener(paymentWatcher)
        payCard.addTextChangedListener(paymentWatcher)
        payCredit.addTextChangedListener(paymentWatcher)

        val statusAdapter = ArrayAdapter.createFromResource(
            this,
            R.array.collection_status_options,
            android.R.layout.simple_spinner_item
        ).apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
        collectionSpinner.adapter = statusAdapter

        val prefs = getSharedPreferences("pos", MODE_PRIVATE)

        val busyJob = lifecycleScope.launch {
            viewModel.isCompletingSale.collect { busy ->
                btnComplete.isEnabled = !busy
                btnComplete.text = if (busy) {
                    getString(R.string.sale_processing)
                } else {
                    getString(R.string.complete_sale)
                }
            }
        }
        val sheetErrorJob = lifecycleScope.launch {
            viewModel.saleEvents.collect { event ->
                if (dialog.isShowing && event is SaleUiEvent.Failed) {
                    messageTv.text = event.message
                    messageTv.visibility = View.VISIBLE
                }
            }
        }
        dialog.setOnDismissListener {
            totalsJob.cancel()
            busyJob.cancel()
            sheetErrorJob.cancel()
            if (activePaymentDialog === dialog) activePaymentDialog = null
        }

        btnComplete.setOnClickListener {
            messageTv.visibility = View.GONE
            currentFocus?.clearFocus()
            var cash = payCash.text.toString().toDoubleOrNull() ?: 0.0
            var mobile = payMobile.text.toString().toDoubleOrNull() ?: 0.0
            var card = payCard.text.toString().toDoubleOrNull() ?: 0.0
            var credit = payCredit.text.toString().toDoubleOrNull() ?: 0.0
            val status = if (collectionSpinner.selectedItemPosition == 1) "to_collect" else "collected"
            val cart = viewModel.cart.value.toList()
            if (cart.isEmpty()) {
                val msg = getString(R.string.cart_empty)
                messageTv.text = msg
                messageTv.visibility = View.VISIBLE
                Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val receiptTotal = viewModel.cartTotals.value.total
            var paid = cash + mobile + card + credit
            if (paid <= 0.005 && receiptTotal > 0) {
                cash = receiptTotal
                paid = receiptTotal
            }
            val receiptCustomer = customerEt.text.toString().trim().takeIf { it.isNotBlank() }
            val receiptPayments = buildList {
                if (cash > 0) add("cash" to cash)
                if (mobile > 0) add("mobile_money" to mobile)
                if (card > 0) add("card" to card)
                if (credit > 0) add("credit" to credit)
            }
            val storeName = prefs.getString("store_name", getString(R.string.store_name))
                ?: getString(R.string.store_name)
            val storePhone = prefs.getString("store_phone", "") ?: ""
            val storeLocation = prefs.getString("store_location", "") ?: ""
            val cashier = prefs.getString("username", null)
            val receipt = if (paid + 0.01 >= receiptTotal) {
                ReceiptPrinter.SaleReceiptRequest(
                    storeName = storeName,
                    cartLines = cart,
                    subtotal = viewModel.subtotal,
                    discountTotal = viewModel.discountTotal,
                    total = receiptTotal,
                    payments = receiptPayments,
                    customerName = receiptCustomer,
                    collectionStatus = status,
                    cashierName = cashier,
                    storePhone = storePhone,
                    storeLocation = storeLocation,
                )
            } else {
                null
            }
            val session = SessionStore(this)
            val token = session.getAccessToken() ?: prefs.getString("token", null)
            val cashierId = session.getUserId().takeIf { it > 0 } ?: 1
            lifecycleScope.launch {
                if (receipt != null) {
                    btnComplete.isEnabled = false
                    btnComplete.text = getString(R.string.printing_receipt)
                    val printed = ReceiptPrinter.printSaleAwait(this@MainActivity, receipt)
                    btnComplete.text = getString(R.string.complete_sale)
                    if (!printed) {
                        btnComplete.isEnabled = true
                        messageTv.text = getString(R.string.receipt_print_required)
                        messageTv.visibility = View.VISIBLE
                        return@launch
                    }
                }
                viewModel.completeSale(
                    authToken = token,
                    cashierId = cashierId,
                    customerName = receiptCustomer,
                    cash = cash,
                    mobile = mobile,
                    card = card,
                    credit = credit,
                    collectionStatus = status,
                    notes = null,
                    receipt = null,
                )
            }
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

    private data class ManualSyncOutcome(
        val masterOk: Boolean,
        val productCount: Int,
        val salesPushed: Int,
        val salesPending: Int,
    )

    /** User-triggered sync: refresh catalog and upload queued sales. */
    private fun runManualSync(prefs: android.content.SharedPreferences, syncButton: android.widget.Button) {
        if (manualSyncInProgress) return
        if (!NetworkUtils.isOnline(this)) {
            Toast.makeText(this, R.string.sync_requires_network, Toast.LENGTH_LONG).show()
            return
        }
        val session = SessionStore(this)
        val token = session.getAccessToken() ?: prefs.getString("token", null)
        if (token.isNullOrBlank()) {
            Toast.makeText(this, R.string.sync_requires_login, Toast.LENGTH_SHORT).show()
            return
        }
        manualSyncInProgress = true
        syncButton.isEnabled = false
        Toast.makeText(this, R.string.sync_in_progress, Toast.LENGTH_SHORT).show()
        lifecycleScope.launch {
            val outcome = withContext(Dispatchers.IO) {
                performManualSync(token)
            }
            manualSyncInProgress = false
            syncButton.isEnabled = true
            val msg = when {
                outcome.salesPushed > 0 && !outcome.masterOk ->
                    getString(R.string.sync_partial, outcome.salesPushed, outcome.salesPending) +
                        " " + getString(R.string.sync_products_failed_hint)
                !outcome.masterOk && outcome.salesPending > 0 ->
                    getString(R.string.sync_master_failed) +
                        " " + getString(R.string.sync_partial, outcome.salesPushed, outcome.salesPending)
                !outcome.masterOk ->
                    getString(R.string.sync_master_failed) +
                        " " + getString(R.string.sync_check_server_url)
                else ->
                    getString(
                        R.string.sync_complete,
                        outcome.productCount,
                        outcome.salesPushed,
                        outcome.salesPending,
                    )
            }
            Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
            triggerSyncWhenOnline()
        }
    }

    private suspend fun performManualSync(token: String): ManualSyncOutcome {
        val bearer = token.trim().let { if (it.startsWith("Bearer ")) it else "Bearer $it" }
        val rawToken = bearer.removePrefix("Bearer ").trim()
        val repo = createSyncRepository(readTimeoutSec = 60)
        val db = AppDatabase.getInstance(this)
        var pushed = 0
        for (item in db.syncQueueDao().getByStatus(SyncQueueEntity.STATUS_PENDING)) {
            repo.pushSale(rawToken, item).onSuccess { pushed++ }
        }
        repo.pushOfflineMutations(rawToken)
        val productsOk = repo.pullProductsAndCustomers(rawToken).isSuccess
        if (productsOk) {
            repo.persistStoreSettings(this@MainActivity, rawToken)
            SessionStore(this).recordOfflineAnchor()
        }
        val stillPending = db.syncQueueDao().getByStatus(SyncQueueEntity.STATUS_PENDING).size
        val productCount = db.productDao().countActive()
        return ManualSyncOutcome(
            masterOk = productsOk,
            productCount = productCount,
            salesPushed = pushed,
            salesPending = stillPending,
        )
    }

    /** Enqueue a one-time sync when online. UI never waits; sync runs in background. */
    private fun triggerSyncWhenOnline() {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val baseUrl = prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
            ?: BuildConfig.DEFAULT_API_BASE_URL
        val token = SessionStore(this).getAccessToken() ?: prefs.getString("token", null)
        if (token.isNullOrBlank()) return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val work = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(constraints)
            .setInputData(
                workDataOf(
                    SyncWorker.KEY_BASE_URL to baseUrl,
                    SyncWorker.KEY_TOKEN to token,
                    SyncWorker.KEY_FULL_CACHE to false,
                ),
            )
            .addTag("pos_sync_on_action")
            .build()
        WorkManager.getInstance(this).enqueueUniqueWork(
            "pos_sync_on_action",
            ExistingWorkPolicy.KEEP,
            work,
        )
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

    /**
     * After SaaS login or register, if the tenant is on a free trial, open the subscription screen once.
     * Skips when offline or status cannot be loaded (e.g. legacy auth without tenant).
     */
    private suspend fun promptTrialSubscriptionAfterAuth() {
        if (!NetworkUtils.isOnline(this)) return
        val bearer = PosAuth.bearer(this) ?: return
        val s = try {
            val resp = withContext(Dispatchers.IO) {
                PosAuth.api(this@MainActivity).getSubscriptionStatus(bearer)
            }
            if (!resp.isSuccessful) return
            resp.body() ?: return
        } catch (_: Exception) {
            return
        }
        SessionStore(this).updateSubscriptionCache(
            status = s.effective_status,
            subscriptionEndIso = s.subscription_end ?: s.trial_end,
            plan = s.plan,
            verifiedMs = System.currentTimeMillis(),
            accessAllowed = s.access_allowed,
            features = s.features,
            effectivePlan = s.effective_plan ?: s.plan,
        )
        if (s.effective_status != "trial") return
        withContext(Dispatchers.Main) {
            startActivity(Intent(this@MainActivity, SubscriptionActivity::class.java))
        }
    }

    private fun refreshSubscriptionWarning(posContainer: View) {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val role = prefs.getString("role", "cashier") ?: "cashier"
        val session = SessionStore(this)
        val sub = session.subscriptionStatus()
        val warnTv = posContainer.findViewById<TextView>(R.id.subscription_banner)
        if (warnTv == null) return
        val show = sub == "trial_expired" || sub == "expired" || sub == "pending_payment"
        warnTv.isVisible = show
        if (show) {
            warnTv.text = getString(R.string.subscription_expired_warning)
            warnTv.setOnClickListener {
                if (WebPosRules.roleCanAccessAdmin(role)) {
                    startActivity(Intent(this, SubscriptionActivity::class.java))
                } else {
                    Toast.makeText(
                        this,
                        getString(R.string.subscription_admin_only),
                        Toast.LENGTH_LONG,
                    ).show()
                }
            }
        }
    }

    private fun refreshSubscriptionFromServer() {
        if (!NetworkUtils.isOnline(this)) return
        val bearer = PosAuth.bearer(this) ?: return
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val resp = PosAuth.api(this@MainActivity).getSubscriptionStatus(bearer)
                if (resp.isSuccessful) {
                    val s = resp.body() ?: return@launch
                    SessionStore(this@MainActivity).updateSubscriptionCache(
                        status = s.effective_status,
                        subscriptionEndIso = s.subscription_end ?: s.trial_end,
                        plan = s.plan,
                        verifiedMs = System.currentTimeMillis(),
                        accessAllowed = s.access_allowed,
                        features = s.features,
                        effectivePlan = s.effective_plan ?: s.plan,
                    )
                    withContext(Dispatchers.Main) {
                        posContainerRef?.let { refreshSubscriptionWarning(it) }
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_NOTIFICATIONS) {
            findViewById<android.widget.Button>(R.id.icon_notifications)?.let { refreshNotificationBadge(it) }
        }
    }

    private fun refreshNotificationBadge(button: android.widget.Button) {
        notificationBadgeJob?.cancel()
        if (!NetworkUtils.isOnline(this)) {
            button.text = "🔔"
            return
        }
        val bearer = PosAuth.bearer(this) ?: run {
            button.text = "🔔"
            return
        }
        notificationBadgeJob = lifecycleScope.launch {
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@MainActivity).getUnreadNotificationCount(bearer)
                }
                val count = if (resp.isSuccessful) resp.body()?.count ?: 0 else 0
                button.text = if (count > 0) "🔔$count" else "🔔"
            } catch (_: Exception) {
                button.text = "🔔"
            }
        }
    }

    override fun onDestroy() {
        notificationBadgeJob?.cancel()
        unregisterConnectivitySyncWatcher()
        super.onDestroy()
    }
}

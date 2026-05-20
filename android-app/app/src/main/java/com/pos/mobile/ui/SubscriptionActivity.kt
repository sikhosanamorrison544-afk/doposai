package com.pos.mobile.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.textfield.TextInputEditText
import com.pos.mobile.R
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.remote.InitiateSubscriptionPaymentDto
import com.pos.mobile.data.remote.SubscriptionPlanDto
import com.pos.mobile.data.remote.SubscriptionStatusDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

class SubscriptionActivity : BaseNativeActivity() {

    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var planGroup: RadioGroup
    private var plans: List<SubscriptionPlanDto> = emptyList()
    private var selectedPlanId = "starter"
    private lateinit var btnPayEcoCash: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.subscription_title), R.layout.activity_subscription)
        refresh = findViewById(R.id.subscription_refresh)
        planGroup = findViewById(R.id.sub_plan_group)
        refresh.setColorSchemeColors(ContextCompat.getColor(this, R.color.primary))

        findViewById<RadioGroup>(R.id.sub_cycle_group).setOnCheckedChangeListener { _, _ ->
            renderPlanOptions()
        }
        btnPayEcoCash = findViewById(R.id.btn_pay_ecocash)
        btnPayEcoCash.setOnClickListener { payEcoCash() }
        if (!WebPosRules.roleCanAccessAdmin(PosAuth.role(this))) {
            btnPayEcoCash.isEnabled = false
            btnPayEcoCash.alpha = 0.5f
            findViewById<TextView>(R.id.sub_message).apply {
                text = getString(R.string.subscription_admin_only)
                visibility = View.VISIBLE
            }
        }
        findViewById<Button>(R.id.btn_billing_history).setOnClickListener {
            startActivity(Intent(this, BillingHistoryActivity::class.java))
        }
        refresh.setOnRefreshListener { loadAll() }
        loadAll()
    }

    private fun loadAll() {
        refresh.isRefreshing = true
        lifecycleScope.launch {
            try {
                if (!PosAuth.requireOnline(this@SubscriptionActivity)) {
                    NativeUi.showError(this@SubscriptionActivity, getString(R.string.billing_requires_network))
                    return@launch
                }
                val bearer = PosAuth.bearer(this@SubscriptionActivity) ?: return@launch
                val api = PosAuth.api(this@SubscriptionActivity)
                val plansResp = withContext(Dispatchers.IO) { api.getSubscriptionPlans() }
                if (plansResp.isSuccessful) {
                    plans = plansResp.body()?.plans.orEmpty()
                    renderPlanOptions()
                }
                val statusResp = withContext(Dispatchers.IO) { api.getSubscriptionStatus(bearer) }
                if (statusResp.isSuccessful) {
                    val s = statusResp.body()!!
                    SessionStore(this@SubscriptionActivity).updateSubscriptionCache(
                        status = s.effective_status,
                        subscriptionEndIso = s.subscription_end ?: s.trial_end,
                        plan = s.plan,
                        verifiedMs = System.currentTimeMillis(),
                        accessAllowed = s.access_allowed,
                        features = s.features,
                        effectivePlan = s.effective_plan ?: s.plan,
                    )
                    bindStatus(s)
                }
            } catch (e: Exception) {
                NativeUi.showError(this@SubscriptionActivity, e.message ?: "Error")
            } finally {
                refresh.isRefreshing = false
            }
        }
    }

    private fun bindStatus(s: SubscriptionStatusDto) {
        val planName = s.plan.replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.getDefault()) else it.toString() }
        val cycle = when (s.billing_cycle?.lowercase(Locale.getDefault())) {
            "monthly" -> getString(R.string.billing_monthly)
            "yearly" -> getString(R.string.billing_yearly)
            else -> getString(R.string.subscription_cycle_not_set)
        }
        findViewById<TextView>(R.id.sub_plan_detail).text =
            getString(R.string.subscription_current_plan, planName, cycle)

        val daysTv = findViewById<TextView>(R.id.sub_days_remaining)
        val days = s.days_remaining
        if (days != null) {
            daysTv.text = getString(R.string.subscription_days_left, days)
            daysTv.isVisible = true
        } else {
            daysTv.text = getString(R.string.subscription_no_period_end)
            daysTv.isVisible = true
        }

        findViewById<TextView>(R.id.sub_status_line).text =
            "${s.effective_status.replace('_', ' ')} · access: ${if (s.access_allowed) "yes" else "no"}"

        val warn = findViewById<TextView>(R.id.sub_warning)
        when {
            !s.access_allowed -> {
                warn.isVisible = true
                warn.text = getString(R.string.subscription_expired_warning)
            }
            s.effective_status == "trial" || s.effective_status == "trial_expired" -> {
                warn.isVisible = true
                warn.text = getString(R.string.subscription_trial_warning, s.trial_end ?: "—")
            }
            else -> warn.isVisible = false
        }
    }

    private fun renderPlanOptions() {
        planGroup.removeAllViews()
        val yearly = findViewById<RadioButton>(R.id.cycle_yearly).isChecked
        val cycle = if (yearly) "yearly" else "monthly"
        plans.forEach { p ->
            val price = if (yearly) p.yearly else p.monthly
            val rb = RadioButton(this).apply {
                text = "${p.name} — $${price?.amount_usd ?: 0.0} / $cycle"
                id = View.generateViewId()
                tag = p.id
                isChecked = p.id == selectedPlanId
            }
            rb.setOnClickListener { selectedPlanId = p.id }
            planGroup.addView(rb)
        }
    }

    private fun payEcoCash() {
        if (!WebPosRules.roleCanAccessAdmin(PosAuth.role(this))) {
            NativeUi.showError(this, getString(R.string.subscription_admin_only))
            return
        }
        val phone = findViewById<TextInputEditText>(R.id.ecocash_phone).text?.toString()?.trim()
        if (phone.isNullOrBlank()) {
            NativeUi.showError(this, getString(R.string.ecocash_phone_required))
            return
        }
        val yearly = findViewById<RadioButton>(R.id.cycle_yearly).isChecked
        val cycle = if (yearly) "yearly" else "monthly"
        val msg = findViewById<TextView>(R.id.sub_message)
        btnPayEcoCash.isEnabled = false
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@SubscriptionActivity)
            if (bearer == null) {
                btnPayEcoCash.isEnabled = true
                NativeUi.showError(this@SubscriptionActivity, getString(R.string.login_error))
                return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@SubscriptionActivity).initiateSubscriptionPayment(
                        bearer,
                        InitiateSubscriptionPaymentDto(
                            plan = selectedPlanId,
                            billing_cycle = cycle,
                            ecocash_phone = phone,
                            channel = "android",
                        ),
                    )
                }
                if (!resp.isSuccessful) {
                    val detail = PosAuth.httpErrorDetail(resp) ?: getString(R.string.payment_failed)
                    NativeUi.bindMessage(msg, detail)
                    NativeUi.showError(this@SubscriptionActivity, detail)
                    return@launch
                }
                val body = resp.body()
                if (body == null) {
                    NativeUi.bindMessage(msg, getString(R.string.payment_failed))
                    return@launch
                }
                if (body.poll_url.isNullOrBlank()) {
                    val err = getString(R.string.payment_failed_no_poll)
                    NativeUi.bindMessage(msg, err)
                    NativeUi.showError(this@SubscriptionActivity, err)
                    return@launch
                }
                startActivity(
                    Intent(this@SubscriptionActivity, PaymentStatusActivity::class.java).apply {
                        putExtra(PaymentStatusActivity.EXTRA_REFERENCE, body.payment_reference)
                        putExtra(PaymentStatusActivity.EXTRA_POLL_URL, body.poll_url)
                        putExtra(
                            PaymentStatusActivity.EXTRA_INSTRUCTIONS,
                            body.instructions ?: getString(R.string.payment_status_hint),
                        )
                    },
                )
            } catch (e: Exception) {
                NativeUi.bindMessage(msg, e.message ?: getString(R.string.payment_failed))
                NativeUi.showError(this@SubscriptionActivity, e.message ?: getString(R.string.payment_failed))
            } finally {
                btnPayEcoCash.isEnabled = WebPosRules.roleCanAccessAdmin(PosAuth.role(this@SubscriptionActivity))
            }
        }
    }
}

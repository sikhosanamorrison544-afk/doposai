package com.pos.mobile.ui

import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.lifecycle.lifecycleScope
import com.pos.mobile.R
import com.pos.mobile.auth.SessionStore
import com.pos.mobile.data.remote.VerifySubscriptionPaymentDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class PaymentStatusActivity : BaseNativeActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.payment_status_title), R.layout.activity_payment_status_content)

        val reference = intent.getStringExtra(EXTRA_REFERENCE).orEmpty()
        val pollUrl = intent.getStringExtra(EXTRA_POLL_URL)
        val instructions = intent.getStringExtra(EXTRA_INSTRUCTIONS)

        findViewById<TextView>(R.id.payment_status_ref).text = reference
        findViewById<TextView>(R.id.payment_status_instructions).text =
            instructions ?: getString(R.string.payment_status_hint)
        val msg = findViewById<TextView>(R.id.payment_status_message)

        findViewById<Button>(R.id.btn_verify_payment).setOnClickListener {
            verify(reference, pollUrl, msg)
        }
        findViewById<Button>(R.id.btn_retry_verify).setOnClickListener {
            lifecycleScope.launch {
                repeat(3) {
                    verify(reference, pollUrl, msg)
                    delay(5000)
                }
            }
        }

        if (!pollUrl.isNullOrBlank()) {
            lifecycleScope.launch {
                delay(3000)
                verify(reference, pollUrl, msg)
            }
        }
    }

    private fun verify(reference: String, pollUrl: String?, msg: TextView) {
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@PaymentStatusActivity) ?: return@launch
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@PaymentStatusActivity).verifySubscriptionPayment(
                        bearer,
                        VerifySubscriptionPaymentDto(reference, pollUrl),
                    )
                }
                if (resp.isSuccessful && resp.body()?.paid == true) {
                    val body = resp.body()!!
                    SessionStore(this@PaymentStatusActivity).updateSubscriptionCache(
                        status = body.effective_status ?: "active",
                        subscriptionEndIso = null,
                        plan = null,
                        verifiedMs = System.currentTimeMillis(),
                        accessAllowed = body.access_allowed ?: true,
                    )
                    NativeUi.bindMessage(msg, getString(R.string.payment_verified_success), isError = false)
                    NativeUi.showSuccess(this@PaymentStatusActivity, getString(R.string.payment_verified_success))
                    finish()
                } else {
                    NativeUi.bindMessage(msg, getString(R.string.payment_not_confirmed_yet))
                }
            } catch (e: Exception) {
                NativeUi.bindMessage(msg, e.message ?: "Verify failed")
            }
        }
    }

    companion object {
        const val EXTRA_REFERENCE = "payment_reference"
        const val EXTRA_POLL_URL = "poll_url"
        const val EXTRA_INSTRUCTIONS = "instructions"
    }
}

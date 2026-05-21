package com.pos.mobile.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.Spinner
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import com.pos.mobile.R
import com.pos.mobile.data.remote.WithdrawalCreateDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class WithdrawalActivity : BaseNativeActivity() {

    private lateinit var reasonSpinner: Spinner
    private lateinit var otherLayout: TextInputLayout
    private lateinit var salarySection: View
    private lateinit var messageTv: TextView
    private lateinit var processBtn: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.withdrawal_title), R.layout.activity_withdrawal)

        reasonSpinner = findViewById(R.id.withdrawal_reason)
        otherLayout = findViewById(R.id.withdrawal_other_layout)
        salarySection = findViewById(R.id.withdrawal_salary_section)
        messageTv = findViewById(R.id.withdrawal_message)
        processBtn = findViewById(R.id.btn_process_withdrawal)

        val reasons = listOf(
            getString(R.string.withdrawal_select_reason),
            "Daily expenses",
            "Buying company assets",
            "Salary",
            "Other",
        )
        reasonSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, reasons)

        reasonSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val reason = reasons.getOrNull(position).orEmpty()
                otherLayout.isVisible = reason == "Other"
                salarySection.isVisible = reason == "Salary"
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        processBtn.setOnClickListener { processWithdrawal() }
        findViewById<Button>(R.id.btn_withdrawal_history).setOnClickListener {
            startActivity(Intent(this, WebViewActivity::class.java).apply {
                putExtra(WebViewActivity.EXTRA_PATH, "/withdrawals/history")
                putExtra(WebViewActivity.EXTRA_TITLE, getString(R.string.withdrawal_history))
            })
        }
    }

    private fun processWithdrawal() {
        NativeUi.bindMessage(messageTv, null)
        if (!PosAuth.requireOnline(this)) {
            NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_requires_network))
            return
        }

        val amount = findViewById<TextInputEditText>(R.id.withdrawal_amount).text?.toString()?.trim()
            ?.toDoubleOrNull()
        val reasonIndex = reasonSpinner.selectedItemPosition
        val reasonLabel = reasonSpinner.selectedItem?.toString().orEmpty()
        val otherReason = findViewById<TextInputEditText>(R.id.withdrawal_other_reason).text?.toString()?.trim().orEmpty()
        val notes = findViewById<TextInputEditText>(R.id.withdrawal_notes).text?.toString()?.trim()

        when {
            amount == null || amount <= 0 -> NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_invalid_amount))
            reasonIndex <= 0 -> NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_reason_required))
            reasonLabel == "Other" && otherReason.isBlank() ->
                NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_other_required))
            reasonLabel == "Salary" && findViewById<TextInputEditText>(R.id.salary_employee_name).text.isNullOrBlank() ->
                NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_employee_required))
            reasonLabel == "Salary" && findViewById<TextInputEditText>(R.id.salary_period).text.isNullOrBlank() ->
                NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_period_required))
            else -> submitWithdrawal(amount, reasonLabel, otherReason, notes)
        }
    }

    private fun submitWithdrawal(amount: Double, reasonLabel: String, otherReason: String, notes: String?) {
        val finalReason = if (reasonLabel == "Other") otherReason else reasonLabel
        val salaryDetails = if (reasonLabel == "Salary") {
            mapOf(
                "employee_name" to findViewById<TextInputEditText>(R.id.salary_employee_name).text.toString().trim(),
                "period" to findViewById<TextInputEditText>(R.id.salary_period).text.toString().trim(),
            )
        } else {
            null
        }

        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@WithdrawalActivity)
            if (bearer.isNullOrBlank()) {
                NativeUi.bindMessage(messageTv, getString(R.string.withdrawal_session_expired))
                return@launch
            }

            processBtn.isEnabled = false
            NativeUi.bindMessage(
                messageTv,
                getString(R.string.withdrawal_processing),
                isError = false,
            )

            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@WithdrawalActivity).createWithdrawal(
                        bearer,
                        WithdrawalCreateDto(
                            amount = amount,
                            reason = finalReason,
                            notes = notes?.ifBlank { null },
                            salary_details = salaryDetails,
                        ),
                    )
                }
                if (!resp.isSuccessful) {
                    val detail = PosAuth.httpErrorDetail(resp) ?: "Withdrawal failed"
                    NativeUi.bindMessage(messageTv, detail)
                    NativeUi.showError(this@WithdrawalActivity, detail)
                    return@launch
                }
                val body = resp.body()
                val msg = getString(R.string.withdrawal_success, body?.receipt_number ?: "—")
                NativeUi.bindMessage(messageTv, msg, isError = false)
                NativeUi.showSuccess(this@WithdrawalActivity, msg)
                printWithdrawalReceipt(
                    withdrawalId = body?.id,
                    receiptNumber = body?.receipt_number,
                    amount = amount,
                    reason = finalReason,
                    notes = notes,
                )
                findViewById<TextInputEditText>(R.id.withdrawal_amount).text?.clear()
                reasonSpinner.setSelection(0)
            } catch (e: Exception) {
                val detail = e.message ?: "Withdrawal failed"
                NativeUi.bindMessage(messageTv, detail)
                NativeUi.showError(this@WithdrawalActivity, detail)
            } finally {
                processBtn.isEnabled = true
            }
        }
    }

    private fun printWithdrawalReceipt(
        withdrawalId: Int?,
        receiptNumber: String?,
        amount: Double,
        reason: String,
        notes: String?,
    ) {
        val prefs = getSharedPreferences("pos", MODE_PRIVATE)
        val storeName = prefs.getString("store_name", getString(R.string.store_name))
            ?: getString(R.string.store_name)
        val username = prefs.getString("username", "") ?: ""
        ReceiptPrinter.printWithdrawal(
            context = this,
            request = ReceiptPrinter.WithdrawalReceiptRequest(
                storeName = storeName,
                withdrawalId = withdrawalId,
                receiptNumber = receiptNumber,
                amount = amount,
                reason = reason,
                cashierName = username.ifBlank { null },
                notes = notes?.ifBlank { null },
                storePhone = prefs.getString("store_phone", null),
                storeLocation = prefs.getString("store_location", null),
            ),
            scope = lifecycleScope,
        )
    }
}

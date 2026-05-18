package com.pos.mobile.ui

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import com.pos.mobile.data.remote.LaybyCustomerDto
import com.pos.mobile.data.remote.LaybyPaymentCreateDto
import com.pos.mobile.data.remote.LaybyTransactionDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LaybyPayFragment : Fragment() {

    private var allCustomers: List<LaybyCustomerDto> = emptyList()
    private var selectedCustomer: LaybyCustomerDto? = null
    private var selectedTransaction: LaybyTransactionDto? = null
    private var transactions: List<LaybyTransactionDto> = emptyList()

    private lateinit var searchInput: EditText
    private lateinit var resultsList: RecyclerView
    private lateinit var selectedTv: TextView
    private lateinit var transactionSpinner: Spinner
    private lateinit var outstandingCard: View
    private lateinit var outstandingTv: TextView
    private lateinit var amountInput: EditText
    private lateinit var methodSpinner: Spinner
    private lateinit var messageTv: TextView
    private lateinit var customerAdapter: LaybyCustomerRowAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = inflater.inflate(R.layout.fragment_layby_payment, container, false)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        searchInput = view.findViewById(R.id.layby_customer_search)
        resultsList = view.findViewById(R.id.layby_customer_results)
        selectedTv = view.findViewById(R.id.layby_selected_customer)
        transactionSpinner = view.findViewById(R.id.layby_transaction_spinner)
        outstandingCard = view.findViewById(R.id.layby_outstanding_card)
        outstandingTv = view.findViewById(R.id.layby_outstanding_text)
        amountInput = view.findViewById(R.id.layby_amount)
        methodSpinner = view.findViewById(R.id.layby_payment_method)
        messageTv = view.findViewById(R.id.layby_pay_message)

        customerAdapter = LaybyCustomerRowAdapter { selectCustomer(it) }
        resultsList.layoutManager = LinearLayoutManager(requireContext())
        resultsList.adapter = customerAdapter

        setupPaymentSpinner(methodSpinner)
        view.findViewById<Button>(R.id.btn_layby_record_payment).setOnClickListener { recordPayment() }

        searchInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                filterCustomers(s?.toString()?.trim().orEmpty())
            }
        })

        transactionSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, v: View?, position: Int, id: Long) {
                if (position <= 0) {
                    selectedTransaction = null
                    outstandingCard.isVisible = false
                    return
                }
                selectedTransaction = transactions.getOrNull(position - 1)
                selectedTransaction?.let { showOutstanding(it) }
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    fun setCustomers(customers: List<LaybyCustomerDto>) {
        allCustomers = customers
        filterCustomers(searchInput.text?.toString()?.trim().orEmpty())
    }

    private fun filterCustomers(query: String) {
        if (query.isEmpty()) {
            resultsList.isVisible = false
            customerAdapter.submit(emptyList())
            return
        }
        val q = query.lowercase()
        val matches = allCustomers.filter {
            it.name.lowercase().contains(q) ||
                (it.phone?.lowercase()?.contains(q) == true)
        }.take(12)
        resultsList.isVisible = matches.isNotEmpty()
        customerAdapter.submit(matches)
    }

    private fun selectCustomer(customer: LaybyCustomerDto) {
        selectedCustomer = customer
        searchInput.setText(customer.name)
        resultsList.isVisible = false
        customerAdapter.submit(emptyList())
        selectedTv.text = customer.name
        selectedTv.isVisible = true
        NativeUi.bindMessage(messageTv, null)
        loadTransactions(customer.id)
    }

    private fun loadTransactions(customerId: Int) {
        if (!PosAuth.requireOnline(requireContext())) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_requires_network))
            return
        }
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(requireContext()) ?: return@launch
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(requireContext()).getLaybyTransactions(
                        bearer,
                        customerId = customerId,
                        status = "active",
                    )
                }
                if (!resp.isSuccessful) {
                    NativeUi.bindMessage(messageTv, resp.message() ?: "Failed to load transactions")
                    return@launch
                }
                transactions = resp.body().orEmpty()
                if (transactions.isEmpty()) {
                    transactionSpinner.isVisible = false
                    outstandingCard.isVisible = false
                    NativeUi.bindMessage(messageTv, getString(R.string.layby_no_active_transactions))
                    return@launch
                }
                val labels = listOf(getString(R.string.layby_transaction)) +
                    transactions.map { "${it.product_name} · ${NativeUi.formatMoney(it.balance)} due" }
                transactionSpinner.adapter = ArrayAdapter(
                    requireContext(),
                    android.R.layout.simple_spinner_dropdown_item,
                    labels,
                )
                transactionSpinner.isVisible = true
                if (transactions.size == 1) {
                    transactionSpinner.setSelection(1)
                }
            } catch (e: Exception) {
                NativeUi.bindMessage(messageTv, e.message ?: "Error loading transactions")
            }
        }
    }

    private fun showOutstanding(txn: LaybyTransactionDto) {
        outstandingCard.isVisible = true
        outstandingTv.text = getString(
            R.string.layby_outstanding_format,
            NativeUi.formatMoney(txn.total_amount),
            NativeUi.formatMoney(txn.paid_amount),
            NativeUi.formatMoney(txn.balance),
        )
    }

    private fun recordPayment() {
        NativeUi.bindMessage(messageTv, null)
        val customer = selectedCustomer
        val txn = selectedTransaction
        if (customer == null) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_select_customer))
            return
        }
        if (txn == null) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_select_transaction))
            return
        }
        if (!PosAuth.requireOnline(requireContext())) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_requires_network))
            return
        }
        val amount = amountInput.text.toString().trim().toDoubleOrNull()
        if (amount == null || amount <= 0) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_invalid_amount))
            return
        }
        if (amount > txn.balance) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_amount_exceeds_balance))
            return
        }
        val apiMethod = paymentMethodValue(methodSpinner.selectedItemPosition)
        if (apiMethod.isBlank()) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_select_payment_method))
            return
        }

        lifecycleScope.launch {
            val bearer = PosAuth.bearer(requireContext()) ?: return@launch
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(requireContext()).createLaybyPayment(
                        bearer,
                        LaybyPaymentCreateDto(
                            transaction_id = txn.id,
                            amount = amount,
                            payment_method = apiMethod,
                        ),
                    )
                }
                if (!resp.isSuccessful) {
                    NativeUi.bindMessage(messageTv, resp.message() ?: "Payment failed")
                    return@launch
                }
                val payment = resp.body()
                NativeUi.bindMessage(
                    messageTv,
                    getString(R.string.layby_payment_recorded, payment?.receipt_number ?: "—"),
                    isError = false,
                )
                NativeUi.showSuccess(requireContext(), getString(R.string.layby_payment_recorded, payment?.receipt_number ?: ""))
                amountInput.text.clear()
                (activity as? LaybyActivity)?.reloadCustomers()
                loadTransactions(customer.id)
            } catch (e: Exception) {
                NativeUi.bindMessage(messageTv, e.message ?: "Payment failed")
            }
        }
    }

    companion object {
        fun setupPaymentSpinner(spinner: Spinner) {
            val ctx = spinner.context
            val labels = listOf(
                ctx.getString(R.string.layby_select_payment_method),
                "Cash",
                "Mobile Money",
                "Card",
            )
            spinner.adapter = ArrayAdapter(ctx, android.R.layout.simple_spinner_dropdown_item, labels)
        }

        private fun paymentMethodValue(position: Int): String = when (position) {
            1 -> "cash"
            2 -> "mobile_money"
            3 -> "card"
            else -> ""
        }
    }
}

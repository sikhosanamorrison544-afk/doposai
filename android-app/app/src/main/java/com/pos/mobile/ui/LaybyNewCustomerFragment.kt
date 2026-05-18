package com.pos.mobile.ui

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.textfield.TextInputEditText
import com.pos.mobile.R
import com.pos.mobile.data.local.AppDatabase
import com.pos.mobile.data.local.entity.ProductEntity
import com.pos.mobile.data.remote.LaybyCustomerCreateDto
import com.pos.mobile.data.remote.LaybyPaymentCreateDto
import com.pos.mobile.data.remote.LaybyTransactionCreateDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LaybyNewCustomerFragment : Fragment() {

    private var selectedProduct: ProductEntity? = null
    private lateinit var productSearch: EditText
    private lateinit var productResults: RecyclerView
    private lateinit var selectedProductTv: TextView
    private lateinit var messageTv: TextView
    private lateinit var methodSpinner: Spinner
    private lateinit var searchAdapter: SearchProductAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = inflater.inflate(R.layout.fragment_layby_new_customer, container, false)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        productSearch = view.findViewById(R.id.new_layby_product_search)
        productResults = view.findViewById(R.id.new_layby_product_results)
        selectedProductTv = view.findViewById(R.id.new_layby_selected_product)
        messageTv = view.findViewById(R.id.layby_new_message)
        methodSpinner = view.findViewById(R.id.new_layby_payment_method)

        LaybyPayFragment.setupPaymentSpinner(methodSpinner)
        searchAdapter = SearchProductAdapter { product ->
            val available = WebPosRules.availableStock(product)
            if (available <= 0) {
                NativeUi.bindMessage(messageTv, "Product is out of stock")
                return@SearchProductAdapter
            }
            selectedProduct = product
            productSearch.setText(product.name)
            productResults.isVisible = false
            searchAdapter.submitList(emptyList())
            selectedProductTv.text = "${product.name} · ${NativeUi.formatMoney(product.sellingPrice)}"
            selectedProductTv.isVisible = true
        }
        productResults.layoutManager = LinearLayoutManager(requireContext())
        productResults.adapter = searchAdapter

        productSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                if (q.length < 2) {
                    productResults.isVisible = false
                    searchAdapter.submitList(emptyList())
                    return
                }
                lifecycleScope.launch {
                    val pattern = "%${q.lowercase()}%"
                    val matches = withContext(Dispatchers.IO) {
                        AppDatabase.getInstance(requireContext()).productDao()
                            .searchActive(pattern)
                            .filter { WebPosRules.availableStock(it) > 0 }
                            .take(10)
                    }
                    productResults.isVisible = matches.isNotEmpty()
                    searchAdapter.submitList(matches)
                }
            }
        })

        view.findViewById<Button>(R.id.btn_layby_create_customer).setOnClickListener {
            createCustomer(view)
        }
    }

    private fun createCustomer(root: View) {
        NativeUi.bindMessage(messageTv, null)
        if (!PosAuth.requireOnline(requireContext())) {
            NativeUi.bindMessage(messageTv, getString(R.string.layby_requires_network))
            return
        }

        val name = root.findViewById<TextInputEditText>(R.id.new_layby_name).text?.toString()?.trim().orEmpty()
        val phone = root.findViewById<TextInputEditText>(R.id.new_layby_phone).text?.toString()?.trim().orEmpty()
        val email = root.findViewById<TextInputEditText>(R.id.new_layby_email).text?.toString()?.trim()
        val address = root.findViewById<TextInputEditText>(R.id.new_layby_address).text?.toString()?.trim().orEmpty()
        val initial = root.findViewById<TextInputEditText>(R.id.new_layby_initial_payment).text?.toString()?.trim()
            ?.toDoubleOrNull()
        val product = selectedProduct

        when {
            name.isBlank() -> NativeUi.bindMessage(messageTv, getString(R.string.layby_name_required))
            phone.isBlank() -> NativeUi.bindMessage(messageTv, getString(R.string.layby_phone_required))
            !email.isNullOrBlank() && !android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches() ->
                NativeUi.bindMessage(messageTv, getString(R.string.layby_invalid_email))
            address.isBlank() -> NativeUi.bindMessage(messageTv, getString(R.string.layby_address_required))
            product == null -> NativeUi.bindMessage(messageTv, getString(R.string.layby_product_required))
            initial == null || initial <= 0 -> NativeUi.bindMessage(messageTv, getString(R.string.layby_initial_required))
            initial > product.sellingPrice -> NativeUi.bindMessage(messageTv, getString(R.string.layby_initial_exceeds_price))
            methodSpinner.selectedItemPosition <= 0 -> NativeUi.bindMessage(messageTv, getString(R.string.layby_select_payment_method))
            else -> submit(name, phone, email, address, product, initial)
        }
    }

    private fun submit(
        name: String,
        phone: String,
        email: String?,
        address: String,
        product: ProductEntity,
        initial: Double,
    ) {
        val method = when (methodSpinner.selectedItemPosition) {
            1 -> "cash"
            2 -> "mobile_money"
            3 -> "card"
            else -> ""
        }
        lifecycleScope.launch {
            val bearer = PosAuth.bearer(requireContext()) ?: return@launch
            val api = PosAuth.api(requireContext())
            try {
                val customerResp = withContext(Dispatchers.IO) {
                    api.createLaybyCustomer(
                        bearer,
                        LaybyCustomerCreateDto(
                            name = name,
                            phone = phone,
                            email = email?.ifBlank { null },
                            address = address,
                            layby_item_name = product.name,
                        ),
                    )
                }
                if (!customerResp.isSuccessful) {
                    NativeUi.bindMessage(messageTv, customerResp.message() ?: "Failed to create customer")
                    return@launch
                }
                val customer = customerResp.body() ?: return@launch

                val txnResp = withContext(Dispatchers.IO) {
                    api.createLaybyTransaction(
                        bearer,
                        LaybyTransactionCreateDto(
                            customer_id = customer.id,
                            product_id = product.id,
                            quantity = 1,
                            notes = "Initial payment: ${NativeUi.formatMoney(initial)}",
                        ),
                    )
                }
                if (!txnResp.isSuccessful) {
                    NativeUi.bindMessage(messageTv, txnResp.message() ?: "Failed to create transaction")
                    return@launch
                }
                val txn = txnResp.body() ?: return@launch

                val payResp = withContext(Dispatchers.IO) {
                    api.createLaybyPayment(
                        bearer,
                        LaybyPaymentCreateDto(
                            transaction_id = txn.id,
                            amount = initial,
                            payment_method = method,
                            notes = "Initial payment",
                        ),
                    )
                }
                if (!payResp.isSuccessful) {
                    NativeUi.bindMessage(messageTv, payResp.message() ?: "Failed to record initial payment")
                    return@launch
                }
                val payment = payResp.body()
                val msg = getString(
                    R.string.layby_customer_created,
                    customer.name,
                    txn.id,
                    payment?.receipt_number ?: "—",
                )
                NativeUi.bindMessage(messageTv, msg, isError = false)
                NativeUi.showSuccess(requireContext(), msg)
                clearForm()
                (activity as? LaybyActivity)?.reloadCustomers()
            } catch (e: Exception) {
                NativeUi.bindMessage(messageTv, e.message ?: "Failed to add customer")
            }
        }
    }

    private fun clearForm() {
        view?.findViewById<TextInputEditText>(R.id.new_layby_name)?.text?.clear()
        view?.findViewById<TextInputEditText>(R.id.new_layby_phone)?.text?.clear()
        view?.findViewById<TextInputEditText>(R.id.new_layby_email)?.text?.clear()
        view?.findViewById<TextInputEditText>(R.id.new_layby_address)?.text?.clear()
        view?.findViewById<TextInputEditText>(R.id.new_layby_initial_payment)?.text?.clear()
        productSearch.text.clear()
        selectedProduct = null
        selectedProductTv.isVisible = false
        methodSpinner.setSelection(0)
    }
}

package com.pos.mobile.ui

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.pos.mobile.R
import com.pos.mobile.data.remote.PaymentInputDto
import com.pos.mobile.data.remote.QuotationConvertRequestDto
import com.pos.mobile.data.remote.QuotationDetailDto
import com.pos.mobile.data.remote.QuotationSummaryDto
import com.pos.mobile.sync.SyncScheduler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class QuotationHistoryActivity : BaseNativeActivity() {

    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var searchEt: EditText
    private lateinit var list: RecyclerView
    private lateinit var emptyTv: TextView
    private lateinit var adapter: QuotationHistoryAdapter
    private var searchJob: Job? = null
    data class HistoryRow(
        val id: Int?,
        val quotationNumber: String,
        val customerName: String?,
        val total: Double,
        val status: String,
        val createdAt: String,
        val isLocalOnly: Boolean,
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.quotation_history_title), R.layout.activity_quotation_history)
        refresh = findViewById(R.id.quotation_history_refresh)
        searchEt = findViewById(R.id.quotation_search)
        list = findViewById(R.id.quotation_history_list)
        emptyTv = findViewById(R.id.quotation_history_empty)
        refresh.setColorSchemeColors(ContextCompat.getColor(this, R.color.button_quotation))

        adapter = QuotationHistoryAdapter { showQuotationActions(it) }
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = adapter

        refresh.setOnRefreshListener { loadQuotations(searchEt.text.toString()) }
        searchEt.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                searchJob?.cancel()
                searchJob = lifecycleScope.launch {
                    delay(350)
                    loadQuotations(s?.toString().orEmpty())
                }
            }
        })

        val initialSearch = intent.getStringExtra(EXTRA_SEARCH).orEmpty()
        if (initialSearch.isNotBlank()) {
            searchEt.setText(initialSearch)
        }
        loadQuotations(initialSearch)
    }

    private fun loadQuotations(query: String) {
        val localRows = QuotationLocalStore.search(this, query).map { e ->
            HistoryRow(
                id = e.serverId,
                quotationNumber = e.quotationNumber,
                customerName = e.customerName,
                total = e.total,
                status = e.status,
                createdAt = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(Date(e.createdAt)),
                isLocalOnly = e.serverId == null,
            )
        }

        if (!PosAuth.requireOnline(this)) {
            refresh.isRefreshing = false
            adapter.submit(localRows)
            updateEmpty(localRows.isEmpty())
            return
        }

        refresh.isRefreshing = true
        lifecycleScope.launch {
            val bearer = when (val auth = PosAuth.ensureBearer(this@QuotationHistoryActivity)) {
                is BearerResult.Ok -> auth.bearer
                else -> {
                    refresh.isRefreshing = false
                    adapter.submit(localRows)
                    updateEmpty(localRows.isEmpty())
                    return@launch
                }
            }
            try {
                val api = PosAuth.api(this@QuotationHistoryActivity)
                val rows = mutableListOf<HistoryRow>()
                val q = query.trim()
                if (q.isNotBlank()) {
                    val lookup = withContext(Dispatchers.IO) {
                        api.lookupQuotation(bearer, q)
                    }
                    if (lookup.isSuccessful && lookup.body() != null) {
                        rows += lookup.body()!!.toHistoryRow()
                    }
                }
                val listResp = withContext(Dispatchers.IO) {
                    api.listQuotations(
                        bearer,
                        search = q.takeIf { it.isNotBlank() },
                        limit = 100,
                    )
                }
                if (listResp.isSuccessful && listResp.body() != null) {
                    for (item in listResp.body()!!.quotations) {
                        if (rows.none { it.quotationNumber.equals(item.quotation_number, true) }) {
                            rows += item.toHistoryRow()
                        }
                    }
                }
                for (local in localRows) {
                    if (rows.none { it.quotationNumber.equals(local.quotationNumber, true) }) {
                        rows += local
                    }
                }
                rows.sortByDescending { it.createdAt }
                adapter.submit(rows)
                updateEmpty(rows.isEmpty())
            } catch (e: Exception) {
                NativeUi.showError(this@QuotationHistoryActivity, e.message ?: "Failed to load")
                adapter.submit(localRows)
                updateEmpty(localRows.isEmpty())
            } finally {
                refresh.isRefreshing = false
            }
        }
    }

    private fun updateEmpty(empty: Boolean) {
        emptyTv.isVisible = empty
        list.isVisible = !empty
    }

    private fun showQuotationActions(row: HistoryRow) {
        val actions = mutableListOf<String>()
        if (row.status == "converted") {
            actions += getString(R.string.quotation_action_reprint)
        } else {
            actions += getString(R.string.quotation_action_convert)
        }
        actions += getString(R.string.quotation_action_pdf)
        if (row.isLocalOnly || row.id != null) {
            when (row.status) {
                "draft", "converted", "local" -> actions += getString(R.string.quotation_action_delete)
            }
        }

        MaterialAlertDialogBuilder(this)
            .setTitle(row.quotationNumber)
            .setItems(actions.toTypedArray()) { _, which ->
                when (actions[which]) {
                    getString(R.string.quotation_action_convert) -> startConvertFlow(row)
                    getString(R.string.quotation_action_reprint) -> reprintReceipt(row)
                    getString(R.string.quotation_action_pdf) -> downloadPdf(row)
                    getString(R.string.quotation_action_delete) -> confirmDelete(row)
                }
            }
            .show()
    }

    private fun startConvertFlow(row: HistoryRow) {
        if (row.id == null) {
            Toast.makeText(this, R.string.quotation_convert_requires_sync, Toast.LENGTH_LONG).show()
            return
        }
        val pad = (16 * resources.displayMetrics.density).toInt()
        val cashEt = EditText(this).apply {
            hint = getString(R.string.quotation_payment_cash)
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText(String.format(Locale.US, "%.2f", row.total))
        }
        val mobileEt = EditText(this).apply {
            hint = getString(R.string.quotation_payment_mobile)
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        val cardEt = EditText(this).apply {
            hint = getString(R.string.quotation_payment_card)
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        val wrap = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
            addView(cashEt)
            addView(mobileEt)
            addView(cardEt)
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.quotation_convert_title)
            .setMessage(getString(R.string.quotation_convert_message, row.quotationNumber))
            .setView(wrap)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.quotation_action_convert) { _, _ ->
                val cash = cashEt.text.toString().toDoubleOrNull() ?: 0.0
                val mobile = mobileEt.text.toString().toDoubleOrNull() ?: 0.0
                val card = cardEt.text.toString().toDoubleOrNull() ?: 0.0
                val payments = QuotationReceiptHelper.paymentsFromAmounts(cash, mobile, card, 0.0)
                if (payments.isEmpty()) {
                    Toast.makeText(this, R.string.quotation_payment_required, Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                convertAndPrint(row.id, payments)
            }
            .show()
    }

    private fun convertAndPrint(quotationId: Int, payments: List<PaymentInputDto>) {
        lifecycleScope.launch {
            val bearer = when (val auth = PosAuth.ensureBearer(this@QuotationHistoryActivity)) {
                is BearerResult.Ok -> auth.bearer
                else -> {
                    Toast.makeText(this@QuotationHistoryActivity, R.string.quotation_session_expired, Toast.LENGTH_LONG).show()
                    return@launch
                }
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@QuotationHistoryActivity).convertQuotationToSale(
                        bearer,
                        quotationId,
                        QuotationConvertRequestDto(payments),
                    )
                }
                if (!resp.isSuccessful || resp.body() == null) {
                    Toast.makeText(
                        this@QuotationHistoryActivity,
                        getString(R.string.quotation_convert_failed, PosAuth.httpErrorDetail(resp)),
                        Toast.LENGTH_LONG,
                    ).show()
                    return@launch
                }
                val receipt = resp.body()!!
                QuotationReceiptHelper.deductLocalStock(this@QuotationHistoryActivity, receipt.items)
                val printed = QuotationReceiptHelper.printReceipt(this@QuotationHistoryActivity, receipt)
                SyncScheduler.enqueueCatalogSync(this@QuotationHistoryActivity)
                Toast.makeText(
                    this@QuotationHistoryActivity,
                    if (printed) R.string.quotation_convert_success else R.string.quotation_convert_no_printer,
                    Toast.LENGTH_LONG,
                ).show()
                offerDeleteAfterConvert(
                    HistoryRow(
                        id = quotationId,
                        quotationNumber = receipt.quotation_number,
                        customerName = receipt.customer_name,
                        total = receipt.total,
                        status = "converted",
                        createdAt = "",
                        isLocalOnly = false,
                    ),
                )
                loadQuotations(searchEt.text.toString())
            } catch (e: Exception) {
                Toast.makeText(
                    this@QuotationHistoryActivity,
                    getString(R.string.quotation_convert_failed, e.message),
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    private fun reprintReceipt(row: HistoryRow) {
        val id = row.id ?: return
        lifecycleScope.launch {
            val bearer = when (val auth = PosAuth.ensureBearer(this@QuotationHistoryActivity)) {
                is BearerResult.Ok -> auth.bearer
                else -> return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@QuotationHistoryActivity).getQuotationReceiptData(bearer, id)
                }
                if (!resp.isSuccessful || resp.body() == null) {
                    Toast.makeText(this@QuotationHistoryActivity, R.string.quotation_reprint_failed, Toast.LENGTH_LONG).show()
                    return@launch
                }
                val printed = QuotationReceiptHelper.printReceipt(this@QuotationHistoryActivity, resp.body()!!)
                Toast.makeText(
                    this@QuotationHistoryActivity,
                    if (printed) R.string.quotation_reprint_success else R.string.quotation_convert_no_printer,
                    Toast.LENGTH_SHORT,
                ).show()
            } catch (e: Exception) {
                Toast.makeText(this@QuotationHistoryActivity, R.string.quotation_reprint_failed, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun downloadPdf(row: HistoryRow) {
        val id = row.id
        if (id == null) {
            Toast.makeText(this, R.string.quotation_pdf_local_only, Toast.LENGTH_LONG).show()
            return
        }
        lifecycleScope.launch {
            val bearer = when (val auth = PosAuth.ensureBearer(this@QuotationHistoryActivity)) {
                is BearerResult.Ok -> auth.bearer
                else -> return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@QuotationHistoryActivity).downloadQuotationPdf(bearer, id)
                }
                if (!resp.isSuccessful || resp.body() == null) {
                    Toast.makeText(this@QuotationHistoryActivity, R.string.quotation_pdf_failed, Toast.LENGTH_LONG).show()
                    return@launch
                }
                val file = withContext(Dispatchers.IO) {
                    val dir = java.io.File(cacheDir, "quotations").apply { mkdirs() }
                    val safe = row.quotationNumber.replace(Regex("[^A-Za-z0-9._-]"), "_")
                    val out = java.io.File(dir, "$safe.pdf")
                    resp.body()!!.byteStream().use { input ->
                        out.outputStream().use { output -> input.copyTo(output) }
                    }
                    out
                }
                val uri = androidx.core.content.FileProvider.getUriForFile(
                    this@QuotationHistoryActivity,
                    "${packageName}.fileprovider",
                    file,
                )
                val intent = android.content.Intent(android.content.Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/pdf")
                    addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                startActivity(android.content.Intent.createChooser(intent, getString(R.string.quotation)))
            } catch (_: Exception) {
                Toast.makeText(this@QuotationHistoryActivity, R.string.quotation_pdf_failed, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun offerDeleteAfterConvert(row: HistoryRow) {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.quotation_delete_after_convert_title)
            .setMessage(getString(R.string.quotation_delete_after_convert_message, row.quotationNumber))
            .setNegativeButton(R.string.quotation_keep_in_history, null)
            .setPositiveButton(R.string.quotation_action_delete) { _, _ -> deleteQuotation(row) }
            .show()
    }

    private fun confirmDelete(row: HistoryRow) {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.quotation_delete_title)
            .setMessage(getString(R.string.quotation_delete_message, row.quotationNumber))
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.quotation_action_delete) { _, _ -> deleteQuotation(row) }
            .show()
    }

    private fun deleteQuotation(row: HistoryRow) {
        QuotationLocalStore.remove(this, row.quotationNumber)
        val id = row.id
        if (id == null) {
            loadQuotations(searchEt.text.toString())
            return
        }
        lifecycleScope.launch {
            val bearer = when (val auth = PosAuth.ensureBearer(this@QuotationHistoryActivity)) {
                is BearerResult.Ok -> auth.bearer
                else -> return@launch
            }
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@QuotationHistoryActivity).deleteQuotation(bearer, id)
                }
                if (resp.isSuccessful) {
                    Toast.makeText(this@QuotationHistoryActivity, R.string.quotation_deleted, Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(
                        this@QuotationHistoryActivity,
                        getString(R.string.quotation_delete_failed, PosAuth.httpErrorDetail(resp)),
                        Toast.LENGTH_LONG,
                    ).show()
                }
            } catch (e: Exception) {
                Toast.makeText(
                    this@QuotationHistoryActivity,
                    getString(R.string.quotation_delete_failed, e.message),
                    Toast.LENGTH_LONG,
                ).show()
            } finally {
                loadQuotations(searchEt.text.toString())
            }
        }
    }

    private fun QuotationSummaryDto.toHistoryRow() = HistoryRow(
        id = id,
        quotationNumber = quotation_number,
        customerName = customer_name,
        total = total,
        status = status,
        createdAt = created_at,
        isLocalOnly = false,
    )

    private fun QuotationDetailDto.toHistoryRow() = HistoryRow(
        id = id,
        quotationNumber = quotation_number,
        customerName = customer_name,
        total = total,
        status = status,
        createdAt = created_at,
        isLocalOnly = false,
    )

    private class QuotationHistoryAdapter(
        private val onClick: (HistoryRow) -> Unit,
    ) : RecyclerView.Adapter<QuotationHistoryAdapter.VH>() {

        private var items: List<HistoryRow> = emptyList()

        fun submit(list: List<HistoryRow>) {
            items = list
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_quotation_history, parent, false)
            return VH(v)
        }

        override fun getItemCount(): Int = items.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            holder.bind(items[position], onClick)
        }

        class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
            private val numberTv: TextView = itemView.findViewById(R.id.quotation_number)
            private val statusTv: TextView = itemView.findViewById(R.id.quotation_status)
            private val customerTv: TextView = itemView.findViewById(R.id.quotation_customer)
            private val totalTv: TextView = itemView.findViewById(R.id.quotation_total)
            private val dateTv: TextView = itemView.findViewById(R.id.quotation_date)

            fun bind(row: HistoryRow, onClick: (HistoryRow) -> Unit) {
                val money = java.text.NumberFormat.getCurrencyInstance(Locale.US)
                numberTv.text = row.quotationNumber
                statusTv.text = row.status
                customerTv.text = row.customerName ?: itemView.context.getString(R.string.quotation_default_customer)
                totalTv.text = money.format(row.total)
                dateTv.text = row.createdAt + if (row.isLocalOnly) " · local" else ""
                itemView.setOnClickListener { onClick(row) }
            }
        }
    }

    companion object {
        const val EXTRA_SEARCH = "search"
    }
}

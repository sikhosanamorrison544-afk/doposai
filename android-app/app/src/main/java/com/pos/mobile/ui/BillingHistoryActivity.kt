package com.pos.mobile.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import com.pos.mobile.data.remote.BillingPaymentDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class BillingHistoryActivity : BaseNativeActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        attachNativeScreen(getString(R.string.billing_history), R.layout.activity_billing_history)
        val list = findViewById<RecyclerView>(R.id.billing_history_list)
        val empty = findViewById<TextView>(R.id.billing_history_empty)
        val adapter = PaymentAdapter()
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = adapter

        lifecycleScope.launch {
            val bearer = PosAuth.bearer(this@BillingHistoryActivity) ?: return@launch
            try {
                val resp = withContext(Dispatchers.IO) {
                    PosAuth.api(this@BillingHistoryActivity).getBillingHistory(bearer)
                }
                val payments = if (resp.isSuccessful) resp.body()?.payments.orEmpty() else emptyList()
                adapter.submit(payments)
                empty.isVisible = payments.isEmpty()
                list.isVisible = payments.isNotEmpty()
            } catch (_: Exception) {
                empty.isVisible = true
            }
        }
    }

    private class PaymentAdapter : RecyclerView.Adapter<PaymentAdapter.VH>() {
        private var items: List<BillingPaymentDto> = emptyList()

        fun submit(list: List<BillingPaymentDto>) {
            items = list
            notifyDataSetChanged()
        }

        override fun getItemCount() = items.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_billing_payment, parent, false)
            return VH(v)
        }

        override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])

        class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
            private val ref = itemView.findViewById<TextView>(R.id.billing_ref)
            private val meta = itemView.findViewById<TextView>(R.id.billing_meta)

            fun bind(p: BillingPaymentDto) {
                ref.text = p.payment_reference
                meta.text = "${p.currency} ${p.amount} · ${p.status} · ${p.created_at}"
            }
        }
    }
}

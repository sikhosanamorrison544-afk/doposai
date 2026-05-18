package com.pos.mobile.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import com.pos.mobile.data.remote.LaybyCustomerDto

class LaybyCustomerRowAdapter(
    private val onSelect: (LaybyCustomerDto) -> Unit,
) : RecyclerView.Adapter<LaybyCustomerRowAdapter.VH>() {

    private var items: List<LaybyCustomerDto> = emptyList()

    fun submit(customers: List<LaybyCustomerDto>) {
        items = customers
        notifyDataSetChanged()
    }

    override fun getItemCount(): Int = items.size

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_layby_customer, parent, false)
        return VH(v, onSelect)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(items[position])
    }

    class VH(itemView: View, private val onSelect: (LaybyCustomerDto) -> Unit) :
        RecyclerView.ViewHolder(itemView) {
        private val row = itemView.findViewById<TextView>(R.id.layby_customer_row)

        fun bind(c: LaybyCustomerDto) {
            val extra = buildList {
                c.phone?.takeIf { it.isNotBlank() }?.let { add(it) }
                c.layby_item_name?.takeIf { it.isNotBlank() }?.let { add(it) }
            }.joinToString(" · ")
            row.text = if (extra.isEmpty()) c.name else "${c.name}\n$extra"
            itemView.setOnClickListener { onSelect(c) }
        }
    }
}

package com.pos.mobile.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import com.pos.mobile.data.local.entity.ProductEntity
import java.text.NumberFormat
import java.util.Locale

class SearchProductAdapter(
    private val onProductClick: (ProductEntity) -> Unit,
) : ListAdapter<ProductEntity, SearchProductAdapter.VH>(Diff) {

    private val format = NumberFormat.getCurrencyInstance(Locale.US)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_search_product, parent, false)
        return VH(v, format, onProductClick)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(getItem(position))
    }

    class VH(
        itemView: android.view.View,
        private val format: NumberFormat,
        private val onProductClick: (ProductEntity) -> Unit,
    ) : RecyclerView.ViewHolder(itemView) {
        private val name = itemView.findViewById<android.widget.TextView>(R.id.search_product_name)
        private val barcode = itemView.findViewById<android.widget.TextView>(R.id.search_product_barcode)
        private val price = itemView.findViewById<android.widget.TextView>(R.id.search_product_price)

        fun bind(p: ProductEntity) {
            val available = WebPosRules.availableStock(p)
            val outOfStock = available <= 0
            name.text = p.name
            barcode.text = buildString {
                append(p.barcode?.takeIf { it.isNotBlank() } ?: "no barcode")
                append(" — ")
                append(format.format(p.sellingPrice))
                if (outOfStock) {
                    append(" (Out of Stock)")
                } else {
                    append(" (Stock: ${available.toInt()})")
                }
            }
            price.visibility = android.view.View.GONE
            val selectable = WebPosRules.canSelectProductInSearch(p)
            itemView.alpha = if (selectable) 1f else 0.55f
            itemView.isEnabled = selectable
            itemView.setOnClickListener {
                if (selectable) onProductClick(p)
            }
            if (outOfStock) {
                name.setTextColor(ContextCompat.getColor(itemView.context, R.color.danger))
            } else {
                name.setTextColor(ContextCompat.getColor(itemView.context, R.color.text_primary))
            }
        }
    }

    object Diff : DiffUtil.ItemCallback<ProductEntity>() {
        override fun areItemsTheSame(a: ProductEntity, b: ProductEntity) = a.id == b.id
        override fun areContentsTheSame(a: ProductEntity, b: ProductEntity) = a == b
    }
}

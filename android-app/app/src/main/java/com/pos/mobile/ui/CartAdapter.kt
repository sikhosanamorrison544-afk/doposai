package com.pos.mobile.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.EditText
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import java.text.NumberFormat
import java.util.Locale

class CartAdapter(
    private val onQtyChange: (index: Int, qty: Int) -> Unit,
    private val onDiscChange: (index: Int, disc: Double) -> Unit,
    private val onRemove: (index: Int) -> Unit
) : ListAdapter<CartLine, CartAdapter.VH>(Diff) {

    private val format = NumberFormat.getCurrencyInstance(Locale.US)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_cart_row, parent, false)
        return VH(v, format, onQtyChange, onDiscChange, onRemove)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(getItem(position), position)
    }

    class VH(
        itemView: android.view.View,
        private val format: NumberFormat,
        private val onQtyChange: (index: Int, qty: Int) -> Unit,
        private val onDiscChange: (index: Int, disc: Double) -> Unit,
        private val onRemove: (index: Int) -> Unit
    ) : RecyclerView.ViewHolder(itemView) {
        private val name = itemView.findViewById<android.widget.TextView>(R.id.cart_item_name)
        private val qty = itemView.findViewById<EditText>(R.id.cart_qty)
        private val price = itemView.findViewById<android.widget.TextView>(R.id.cart_price)
        private val disc = itemView.findViewById<EditText>(R.id.cart_disc)
        private val total = itemView.findViewById<android.widget.TextView>(R.id.cart_total)
        private val remove = itemView.findViewById<android.widget.ImageButton>(R.id.cart_remove)

        fun bind(line: CartLine, index: Int) {
            name.text = line.product.name
            qty.setText(line.quantity.toString())
            price.text = format.format(line.product.sellingPrice)
            disc.setText(line.discount.toInt().toString())
            total.text = format.format(line.lineTotal)
            qty.setOnFocusChangeListener { _, hasFocus ->
                if (!hasFocus) {
                    val v = qty.text.toString().toIntOrNull() ?: 1
                    onQtyChange(index, maxOf(1, v))
                }
            }
            disc.setOnFocusChangeListener { _, hasFocus ->
                if (!hasFocus) {
                    val v = disc.text.toString().toDoubleOrNull() ?: 0.0
                    onDiscChange(index, maxOf(0.0, v))
                }
            }
            remove.setOnClickListener { onRemove(index) }
        }
    }

    object Diff : DiffUtil.ItemCallback<CartLine>() {
        override fun areItemsTheSame(a: CartLine, b: CartLine) = a.product.id == b.product.id
        override fun areContentsTheSame(a: CartLine, b: CartLine) =
            a.quantity == b.quantity && a.discount == b.discount
    }
}

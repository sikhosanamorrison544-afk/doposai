package com.pos.mobile.ui

import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.EditText
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import java.text.NumberFormat
import java.util.Locale

class CartAdapter(
    private val onQtyChange: (index: Int, qty: Int) -> Unit,
    private val onDiscChange: (index: Int, disc: Double) -> Unit,
    private val onRemove: (index: Int) -> Unit,
) : ListAdapter<CartLine, CartAdapter.VH>(Diff) {

    private val format = NumberFormat.getCurrencyInstance(Locale.US)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_cart_row, parent, false)
        return VH(v, format, onQtyChange, onDiscChange, onRemove)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(getItem(position))
    }

    /** Flush visible row editors into the ViewModel (e.g. before checkout). */
    fun commitVisibleEdits(recyclerView: RecyclerView) {
        for (i in 0 until recyclerView.childCount) {
            val child = recyclerView.getChildAt(i)
            (recyclerView.getChildViewHolder(child) as? VH)?.commitEdits()
        }
    }

    class VH(
        itemView: android.view.View,
        private val format: NumberFormat,
        private val onQtyChange: (index: Int, qty: Int) -> Unit,
        private val onDiscChange: (index: Int, disc: Double) -> Unit,
        private val onRemove: (index: Int) -> Unit,
    ) : RecyclerView.ViewHolder(itemView) {
        private val name = itemView.findViewById<android.widget.TextView>(R.id.cart_item_name)
        private val qty = itemView.findViewById<EditText>(R.id.cart_qty)
        private val price = itemView.findViewById<android.widget.TextView>(R.id.cart_price)
        private val disc = itemView.findViewById<EditText>(R.id.cart_disc)
        private val total = itemView.findViewById<android.widget.TextView>(R.id.cart_total)
        private val remove = itemView.findViewById<android.widget.ImageButton>(R.id.cart_remove)
        private var suppressTextWatchers = false

        init {
            qty.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    if (suppressTextWatchers) return
                    val pos = adapterPosition
                    if (pos == RecyclerView.NO_POSITION) return
                    val v = s?.toString()?.toIntOrNull() ?: 1
                    val normalized = CartMath.normalizedQty(v)
                    if (normalized.toString() != s?.toString()) {
                        suppressTextWatchers = true
                        qty.setText(normalized.toString())
                        qty.setSelection(qty.text.length)
                        suppressTextWatchers = false
                    }
                    onQtyChange(pos, normalized)
                    updateLineTotalPreview(pos, normalized)
                }
            })
            disc.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    if (suppressTextWatchers) return
                    val pos = adapterPosition
                    if (pos == RecyclerView.NO_POSITION) return
                    val v = s?.toString()?.toDoubleOrNull() ?: 0.0
                    val normalized = CartMath.normalizedDiscount(v)
                    if (normalized.toInt().toString() != s?.toString()?.trim()) {
                        suppressTextWatchers = true
                        disc.setText(normalized.toInt().toString())
                        disc.setSelection(disc.text.length)
                        suppressTextWatchers = false
                    }
                    onDiscChange(pos, normalized)
                    updateLineTotalPreview(pos)
                }
            })
            remove.setOnClickListener {
                val pos = adapterPosition
                if (pos != RecyclerView.NO_POSITION) onRemove(pos)
            }
        }

        fun bind(line: CartLine) {
            suppressTextWatchers = true
            name.text = line.product.name
            qty.setText(line.quantity.toString())
            price.text = format.format(line.product.sellingPrice)
            disc.setText(line.discount.toInt().toString())
            total.text = format.format(line.lineTotal)
            applyStockStyle(line)
            suppressTextWatchers = false
        }

        fun commitEdits() {
            val pos = adapterPosition
            if (pos == RecyclerView.NO_POSITION) return
            val q = qty.text.toString().toIntOrNull() ?: 1
            val d = disc.text.toString().toDoubleOrNull() ?: 0.0
            onQtyChange(pos, CartMath.normalizedQty(q))
            onDiscChange(pos, CartMath.normalizedDiscount(d))
        }

        private fun updateLineTotalPreview(pos: Int, qtyOverride: Int? = null) {
            val rv = itemView.parent as? RecyclerView ?: return
            val adapter = rv.adapter as? CartAdapter ?: return
            val line = adapter.currentList.getOrNull(pos) ?: return
            val q = qtyOverride ?: qty.text.toString().toIntOrNull() ?: line.quantity
            val d = disc.text.toString().toDoubleOrNull() ?: line.discount
            val preview = line.product.sellingPrice * CartMath.normalizedQty(q) - CartMath.normalizedDiscount(d)
            total.text = format.format(preview)
            applyStockStyle(line.copy(quantity = CartMath.normalizedQty(q)))
        }

        private fun applyStockStyle(line: CartLine) {
            val available = WebPosRules.availableStock(line.product)
            val over = line.quantity > available && available > 0
            val out = available <= 0
            val warnColor = ContextCompat.getColor(itemView.context, R.color.danger)
            val defaultBg = ContextCompat.getColor(itemView.context, android.R.color.transparent)
            if (over || out) {
                qty.setBackgroundColor(0xFFFEE2E2.toInt())
                qty.setTextColor(warnColor)
            } else {
                qty.setBackgroundColor(defaultBg)
                qty.setTextColor(ContextCompat.getColor(itemView.context, R.color.text_primary))
            }
        }
    }

    object Diff : DiffUtil.ItemCallback<CartLine>() {
        override fun areItemsTheSame(a: CartLine, b: CartLine) = a.product.id == b.product.id
        override fun areContentsTheSame(a: CartLine, b: CartLine) =
            a.quantity == b.quantity && a.discount == b.discount
    }
}

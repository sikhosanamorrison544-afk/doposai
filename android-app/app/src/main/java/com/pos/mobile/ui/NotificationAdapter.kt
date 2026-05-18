package com.pos.mobile.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.recyclerview.widget.RecyclerView
import com.pos.mobile.R
import com.pos.mobile.data.remote.NotificationDto

class NotificationAdapter(
    private val onMarkRead: (NotificationDto) -> Unit,
) : RecyclerView.Adapter<NotificationAdapter.VH>() {

    private var items: List<NotificationDto> = emptyList()

    fun submit(notifications: List<NotificationDto>) {
        items = notifications
        notifyDataSetChanged()
    }

    override fun getItemCount(): Int = items.size

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_notification, parent, false)
        return VH(v, onMarkRead)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(items[position])
    }

    class VH(itemView: View, private val onMarkRead: (NotificationDto) -> Unit) :
        RecyclerView.ViewHolder(itemView) {
        private val typeTv = itemView.findViewById<TextView>(R.id.notification_type)
        private val messageTv = itemView.findViewById<TextView>(R.id.notification_message)
        private val productTv = itemView.findViewById<TextView>(R.id.notification_product)
        private val unreadDot = itemView.findViewById<View>(R.id.notification_unread_dot)

        fun bind(n: NotificationDto) {
            typeTv.text = n.type.replace('_', ' ').uppercase()
            messageTv.text = n.message
            if (!n.product_name.isNullOrBlank()) {
                productTv.text = n.product_name
                productTv.isVisible = true
            } else {
                productTv.isVisible = false
            }
            unreadDot.isVisible = !n.is_read
            val alpha = if (n.is_read) 0.65f else 1f
            itemView.alpha = alpha
            itemView.setOnClickListener {
                if (!n.is_read) onMarkRead(n)
            }
        }
    }
}

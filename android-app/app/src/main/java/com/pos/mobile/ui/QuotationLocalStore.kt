package com.pos.mobile.ui

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Persists offline/device-only quotation records for local history search. */
object QuotationLocalStore {

    private const val PREFS = "pos"
    private const val KEY = "quotation_history_json"

    data class Entry(
        val localKey: String,
        val serverId: Int?,
        val quotationNumber: String,
        val customerName: String?,
        val total: Double,
        val status: String,
        val createdAt: Long,
        val itemsJson: String,
    )

    fun save(
        context: Context,
        quotationNumber: String,
        customerName: String?,
        total: Double,
        serverId: Int? = null,
        status: String = "draft",
        itemsJson: String = "[]",
    ) {
        val list = loadAll(context).toMutableList()
        list.removeAll { it.quotationNumber.equals(quotationNumber, ignoreCase = true) }
        list.add(
            0,
            Entry(
                localKey = quotationNumber,
                serverId = serverId,
                quotationNumber = quotationNumber,
                customerName = customerName,
                total = total,
                status = status,
                createdAt = System.currentTimeMillis(),
                itemsJson = itemsJson,
            ),
        )
        persist(context, list)
    }

    fun remove(context: Context, quotationNumber: String) {
        val list = loadAll(context).filterNot {
            it.quotationNumber.equals(quotationNumber, ignoreCase = true)
        }
        persist(context, list)
    }

    fun loadAll(context: Context): List<Entry> {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY, null) ?: return emptyList()
        return try {
            val arr = JSONArray(raw)
            buildList {
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    add(
                        Entry(
                            localKey = o.getString("localKey"),
                            serverId = o.optInt("serverId").takeIf { it > 0 },
                            quotationNumber = o.getString("quotationNumber"),
                            customerName = o.optString("customerName", "").takeIf { it.isNotBlank() },
                            total = o.getDouble("total"),
                            status = o.optString("status", "draft"),
                            createdAt = o.getLong("createdAt"),
                            itemsJson = o.optString("itemsJson", "[]"),
                        ),
                    )
                }
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun search(context: Context, query: String): List<Entry> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return loadAll(context)
        return loadAll(context).filter {
            it.quotationNumber.lowercase().contains(q) ||
                (it.customerName?.lowercase()?.contains(q) == true)
        }
    }

    fun cartItemsJson(cart: List<CartLine>): String {
        val arr = JSONArray()
        for (line in cart) {
            arr.put(
                JSONObject()
                    .put("product_id", line.product.id)
                    .put("product_name", line.product.name)
                    .put("quantity", line.quantity)
                    .put("unit_price", line.product.sellingPrice)
                    .put("discount", line.discount)
                    .put("line_total", line.lineTotal),
            )
        }
        return arr.toString()
    }

    private fun persist(context: Context, list: List<Entry>) {
        val arr = JSONArray()
        for (e in list.take(500)) {
            arr.put(
                JSONObject()
                    .put("localKey", e.localKey)
                    .put("serverId", e.serverId ?: 0)
                    .put("quotationNumber", e.quotationNumber)
                    .put("customerName", e.customerName ?: "")
                    .put("total", e.total)
                    .put("status", e.status)
                    .put("createdAt", e.createdAt)
                    .put("itemsJson", e.itemsJson),
            )
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY, arr.toString())
            .apply()
    }
}

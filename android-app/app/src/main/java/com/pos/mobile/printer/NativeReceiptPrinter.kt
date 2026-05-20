package com.pos.mobile.printer

import android.content.Context
import org.json.JSONObject

object NativeReceiptPrinter {

    private fun enrichStoreFromPrefs(context: Context, json: JSONObject) {
        val prefs = context.getSharedPreferences("pos", Context.MODE_PRIVATE)
        var store = json.optJSONObject("store")
        if (store == null) {
            store = JSONObject()
            json.put("store", store)
        }
        if (!store.optString("store_name").isNotBlank()) {
            store.put(
                "store_name",
                prefs.getString("store_name", "POS") ?: "POS",
            )
        }
        if (!store.optString("store_phone").isNotBlank()) {
            store.put("store_phone", prefs.getString("store_phone", "") ?: "")
        }
        if (!store.optString("store_location").isNotBlank()) {
            store.put("store_location", prefs.getString("store_location", "") ?: "")
        }
    }

    suspend fun printSaleFromJson(context: Context, json: String, transport: String? = null): Result<Unit> {
        val obj = JSONObject(json)
        enrichStoreFromPrefs(context, obj)
        val width = PrinterPreferences.getPaperWidth(context)
        val data = EscPosReceiptBuilder.parseSaleJson(obj, width)
        return ThermalPrintService.print(context, data, transport)
    }

    suspend fun printWithdrawalFromJson(context: Context, json: String, transport: String? = null): Result<Unit> {
        val obj = JSONObject(json)
        enrichStoreFromPrefs(context, obj)
        val width = PrinterPreferences.getPaperWidth(context)
        val data = EscPosReceiptBuilder.parseWithdrawalJson(obj, width)
        return ThermalPrintService.print(context, data, transport)
    }

    suspend fun printTest(context: Context, storeName: String): Result<Unit> {
        val width = PrinterPreferences.getPaperWidth(context)
        val data = EscPosReceiptBuilder(width).buildTestReceipt(storeName)
        return ThermalPrintService.print(context, data)
    }
}

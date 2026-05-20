package com.pos.mobile.printer

import android.content.Context
import org.json.JSONObject

object NativeReceiptPrinter {

    suspend fun printSaleFromJson(context: Context, json: String, transport: String? = null): Result<Unit> {
        val obj = JSONObject(json)
        val width = PrinterPreferences.getPaperWidth(context)
        val data = EscPosReceiptBuilder.parseSaleJson(obj, width)
        return ThermalPrintService.print(context, data, transport)
    }

    suspend fun printWithdrawalFromJson(context: Context, json: String, transport: String? = null): Result<Unit> {
        val obj = JSONObject(json)
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

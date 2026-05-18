package com.pos.mobile.printer

import android.webkit.JavascriptInterface
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.pos.mobile.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Exposed to WebView pages as `PosAndroidPrint` for thermal receipt printing
 * over Bluetooth or USB (ESC/POS).
 */
class PosAndroidPrintBridge(
    private val activity: AppCompatActivity,
    private val scope: CoroutineScope,
) {

    @JavascriptInterface
    fun isAvailable(): String = JSONObject().apply {
        put("native", true)
        put("configured", PrinterPreferences.isConfigured(activity))
        put("transport", PrinterPreferences.getTransport(activity).name.lowercase())
        put("paperWidth", PrinterPreferences.getPaperWidth(activity))
    }.toString()

    @JavascriptInterface
    fun printSaleReceipt(json: String): String = enqueuePrint("sale", json)

    @JavascriptInterface
    fun printWithdrawalReceipt(json: String): String = enqueuePrint("withdrawal", json)

    private fun enqueuePrint(kind: String, json: String): String {
        if (!PrinterPreferences.isConfigured(activity)) {
            return JSONObject().apply {
                put("ok", false)
                put("error", "no_printer")
            }.toString()
        }
        scope.launch {
            try {
                val result = when (kind) {
                    "withdrawal" -> NativeReceiptPrinter.printWithdrawalFromJson(activity, json)
                    else -> NativeReceiptPrinter.printSaleFromJson(activity, json)
                }
                if (result.isFailure) {
                    withContext(Dispatchers.Main) {
                        if (!activity.isFinishing && !activity.isDestroyed) {
                            Toast.makeText(
                                activity,
                                activity.getString(
                                    R.string.printer_failed,
                                    result.exceptionOrNull()?.message ?: "error",
                                ),
                                Toast.LENGTH_LONG,
                            ).show()
                        }
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("PosAndroidPrint", "Print failed", e)
                withContext(Dispatchers.Main) {
                    if (!activity.isFinishing && !activity.isDestroyed) {
                        Toast.makeText(
                            activity,
                            activity.getString(R.string.printer_failed, e.message ?: "error"),
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }
            }
        }
        return JSONObject().apply {
            put("ok", true)
            put("async", true)
        }.toString()
    }
}

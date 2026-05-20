package com.pos.mobile.ui

import android.app.Activity
import android.content.Context
import android.print.PrintAttributes
import android.print.PrintManager
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.pos.mobile.R
import com.pos.mobile.printer.EscPosReceiptBuilder
import com.pos.mobile.printer.PrinterPreferences
import com.pos.mobile.printer.PrinterSetupDialog
import com.pos.mobile.printer.PrinterTransport
import com.pos.mobile.printer.ThermalPrintService
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object ReceiptPrinter {

    private const val TAG = "ReceiptPrinter"

    data class SaleReceiptRequest(
        val storeName: String,
        val cartLines: List<CartLine>,
        val subtotal: Double,
        val discountTotal: Double,
        val total: Double,
        val payments: List<Pair<String, Double>>,
        val customerName: String?,
        val collectionStatus: String,
        val cashierName: String?,
        val saleId: Int? = null,
        val storePhone: String? = null,
        val storeLocation: String? = null,
    )

    fun printSale(
        context: Context,
        storeName: String,
        cartLines: List<CartLine>,
        subtotal: Double,
        discountTotal: Double,
        total: Double,
        payments: List<Pair<String, Double>>,
        customerName: String?,
        collectionStatus: String,
        cashierName: String?,
        saleId: Int? = null,
        scope: CoroutineScope? = null,
    ) {
        printSale(
            context,
            SaleReceiptRequest(
                storeName, cartLines, subtotal, discountTotal, total,
                payments, customerName, collectionStatus, cashierName, saleId,
            ),
            scope,
        )
    }

    fun printSale(
        context: Context,
        request: SaleReceiptRequest,
        scope: CoroutineScope? = null,
    ) {
        val activity = context as? Activity
        if (activity == null || activity.isFinishing) return

        if (PrinterPreferences.isConfigured(context)) {
            val appActivity = activity as? AppCompatActivity
            val printScope = scope ?: appActivity?.lifecycleScope
            if (printScope != null && appActivity != null) {
                val handler = CoroutineExceptionHandler { _, e ->
                    Log.e(TAG, "Print coroutine failed", e)
                    showError(activity, e.message ?: "Print failed")
                }
                val startPrint: () -> Unit = {
                    printScope.launch(handler) {
                        printSaleThermal(activity, request)
                    }
                }
                if (PrinterPreferences.getTransport(context) == PrinterTransport.BLUETOOTH) {
                    PrinterSetupDialog.runWithBluetoothPermission(appActivity, startPrint)
                } else {
                    startPrint.invoke()
                }
                return
            }
        }
        printSaleSystem(activity, request)
    }

    private suspend fun printSaleThermal(activity: Activity, request: SaleReceiptRequest) {
        try {
            val width = PrinterPreferences.getPaperWidth(activity)
            val data = EscPosReceiptBuilder(width).buildSaleReceipt(
                storeName = request.storeName,
                cartLines = request.cartLines,
                subtotal = request.subtotal,
                discountTotal = request.discountTotal,
                total = request.total,
                payments = request.payments,
                customerName = request.customerName,
                collectionStatus = request.collectionStatus,
                cashierName = request.cashierName,
                saleId = request.saleId,
                storePhone = request.storePhone,
                storeLocation = request.storeLocation,
            )
            val result = ThermalPrintService.print(activity, data)
            withContext(Dispatchers.Main) {
                if (result.isSuccess) return@withContext
                val msg = result.exceptionOrNull()?.message ?: "Print failed"
                Log.w(TAG, "Thermal print failed: $msg")
                showError(activity, msg)
                // Do not fall back to system print — WebView often crashes on POS hardware
            }
        } catch (e: Exception) {
            Log.e(TAG, "printSaleThermal error", e)
            withContext(Dispatchers.Main) {
                showError(activity, e.message ?: "Print failed")
            }
        }
    }

    private fun printSaleSystem(activity: Activity, request: SaleReceiptRequest) {
        if (activity.isFinishing || activity.isDestroyed) return
        activity.runOnUiThread {
            if (activity.isFinishing || activity.isDestroyed) return@runOnUiThread
            try {
                val lines = buildReceiptTextLines(request)
                val printManager = activity.getSystemService(Context.PRINT_SERVICE) as? PrintManager
                    ?: return@runOnUiThread
                val adapter = ReceiptPrintDocumentAdapter(
                    activity.applicationContext,
                    "Sale receipt",
                    lines,
                )
                printManager.print(
                    "Sale receipt",
                    adapter,
                    PrintAttributes.Builder().build(),
                )
            } catch (e: Exception) {
                Log.e(TAG, "System print failed", e)
                showError(activity, e.message ?: "Print failed")
            }
        }
    }

    private fun showError(activity: Activity, message: String) {
        if (activity.isFinishing || activity.isDestroyed) return
        activity.runOnUiThread {
            Toast.makeText(
                activity,
                activity.getString(R.string.printer_failed, message),
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    private fun buildReceiptTextLines(request: SaleReceiptRequest): List<String> {
        val df = SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault())
        val lines = mutableListOf<String>()
        lines.add(request.storeName.uppercase())
        lines.add((request.storeLocation ?: "").ifBlank { "" })
        lines.add("Tel: ${request.storePhone ?: ""}")
        lines.add("=" .repeat(32))
        if (request.saleId != null) lines.add("Sale #: ${request.saleId}")
        lines.add("Date: ${df.format(Date())}")
        if (!request.cashierName.isNullOrBlank()) lines.add("Cashier: ${request.cashierName}")
        if (!request.customerName.isNullOrBlank()) lines.add("Customer: ${request.customerName}")
        if (request.collectionStatus == "to_collect") {
            lines.add("STATUS: COLLECTION PENDING")
        } else {
            lines.add("STATUS: COLLECTED")
        }
        lines.add("-".repeat(32))
        lines.add("ITEMS:")
        for (line in request.cartLines) {
            val qty = line.quantity.coerceAtLeast(1)
            lines.add(line.product.name.take(32))
            lines.add(
                "  $qty x ${"%.2f".format(Locale.US, line.product.sellingPrice)} = " +
                    "${"%.2f".format(Locale.US, line.lineTotal)}",
            )
        }
        lines.add("-".repeat(32))
        lines.add("Subtotal:     ${"%.2f".format(Locale.US, request.subtotal).padStart(10)}")
        if (request.discountTotal > 0.005) {
            lines.add("Discount:     ${"%.2f".format(Locale.US, request.discountTotal).padStart(10)}")
        }
        lines.add("TOTAL:        ${"%.2f".format(Locale.US, request.total).padStart(10)}")
        lines.add("PAYMENT:")
        var paid = 0.0
        for ((method, amount) in request.payments) {
            paid += amount
            val label = formatMethod(method).take(15).padEnd(15)
            lines.add("$label ${"%.2f".format(Locale.US, amount).padStart(10)}")
        }
        val change = paid - request.total
        if (change > 0.005) {
            lines.add("CHANGE:       ${"%.2f".format(Locale.US, change).padStart(10)}")
        }
        lines.add("=" .repeat(32))
        lines.add("Thank you for shopping with us!")
        return lines
    }

    private fun formatMethod(method: String): String = when (method) {
        "cash" -> "Cash"
        "mobile_money" -> "Mobile Money"
        "card" -> "Card"
        "credit" -> "Credit"
        else -> method.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }

    data class WithdrawalReceiptRequest(
        val storeName: String,
        val withdrawalId: Int?,
        val receiptNumber: String?,
        val amount: Double,
        val reason: String,
        val cashierName: String?,
        val notes: String?,
        val storePhone: String? = null,
        val storeLocation: String? = null,
    )

    fun printWithdrawal(
        context: Context,
        request: WithdrawalReceiptRequest,
        scope: CoroutineScope? = null,
    ) {
        val activity = context as? Activity ?: return
        if (activity.isFinishing) return

        if (PrinterPreferences.isConfigured(context)) {
            val appActivity = activity as? AppCompatActivity
            val printScope = scope ?: appActivity?.lifecycleScope
            if (printScope != null && appActivity != null) {
                val handler = CoroutineExceptionHandler { _, e ->
                    Log.e(TAG, "Withdrawal print failed", e)
                    showError(activity, e.message ?: "Print failed")
                }
                val startPrint: () -> Unit = {
                    printScope.launch(handler) {
                        printWithdrawalThermal(activity, request)
                    }
                }
                if (PrinterPreferences.getTransport(context) == PrinterTransport.BLUETOOTH) {
                    PrinterSetupDialog.runWithBluetoothPermission(appActivity, startPrint)
                } else {
                    startPrint.invoke()
                }
                return
            }
        }
        showError(activity, activity.getString(R.string.printer_none_selected))
    }

    private suspend fun printWithdrawalThermal(activity: Activity, request: WithdrawalReceiptRequest) {
        try {
            val width = PrinterPreferences.getPaperWidth(activity)
            val data = EscPosReceiptBuilder(width).buildWithdrawalReceipt(
                storeName = request.storeName,
                withdrawalId = request.withdrawalId,
                receiptNumber = request.receiptNumber,
                amount = request.amount,
                reason = request.reason,
                cashierName = request.cashierName,
                notes = request.notes,
                storePhone = request.storePhone,
                storeLocation = request.storeLocation,
            )
            val result = ThermalPrintService.print(activity, data)
            withContext(Dispatchers.Main) {
                if (result.isSuccess) return@withContext
                val msg = result.exceptionOrNull()?.message ?: "Print failed"
                Log.w(TAG, "Withdrawal thermal print failed: $msg")
                showError(activity, msg)
            }
        } catch (e: Exception) {
            Log.e(TAG, "printWithdrawalThermal error", e)
            withContext(Dispatchers.Main) {
                showError(activity, e.message ?: "Print failed")
            }
        }
    }
}

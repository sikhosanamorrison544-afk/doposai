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
import com.pos.mobile.printer.SaleReceiptIds
import com.pos.mobile.printer.PrinterPreferences
import com.pos.mobile.printer.PrinterSetupDialog
import com.pos.mobile.printer.PrinterTransport
import com.pos.mobile.printer.ThermalPrintService
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlin.coroutines.resume
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
        val saleLocalId: Long? = null,
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

    /**
     * Print receipt and wait for result. Use before completing a sale (print first, then charge).
     */
    suspend fun printSaleAwait(activity: AppCompatActivity, request: SaleReceiptRequest): Boolean {
        if (activity.isFinishing || activity.isDestroyed) return false
        if (!PrinterPreferences.isConfigured(activity)) {
            withContext(Dispatchers.Main) {
                Toast.makeText(
                    activity,
                    activity.getString(R.string.printer_none_selected),
                    Toast.LENGTH_LONG,
                ).show()
                PrinterSetupDialog.show(activity, activity.lifecycleScope, request.storeName)
            }
            return false
        }
        return try {
            withTimeout(45_000) {
                suspendCancellableCoroutine { cont ->
                    val handler = CoroutineExceptionHandler { _, e ->
                        Log.e(TAG, "printSaleAwait failed", e)
                        if (cont.isActive) cont.resume(false)
                    }
                    val startPrint: () -> Unit = {
                        activity.lifecycleScope.launch(handler) {
                            val ok = printSaleThermalResult(activity, request)
                            if (cont.isActive) cont.resume(ok)
                        }
                    }
                    if (PrinterPreferences.getTransport(activity) == PrinterTransport.BLUETOOTH) {
                        PrinterSetupDialog.runWithBluetoothPermission(activity, startPrint)
                    } else {
                        startPrint()
                    }
                }
            }
        } catch (_: TimeoutCancellationException) {
            withContext(Dispatchers.Main) {
                showError(activity, activity.getString(R.string.printer_failed, "timed out"))
            }
            false
        }
    }

    private suspend fun printSaleThermalResult(activity: Activity, request: SaleReceiptRequest): Boolean {
        return try {
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
                saleLocalId = request.saleLocalId,
                storePhone = request.storePhone,
                storeLocation = request.storeLocation,
            )
            val result = ThermalPrintService.print(activity, data)
            if (result.isSuccess) return true
            val msg = result.exceptionOrNull()?.message ?: "Print failed"
            Log.w(TAG, "Thermal print failed: $msg")
            withContext(Dispatchers.Main) { showError(activity, msg) }
            printSaleSystemBlocking(activity, request)
        } catch (e: Exception) {
            Log.e(TAG, "printSaleThermalResult error", e)
            withContext(Dispatchers.Main) { showError(activity, e.message ?: "Print failed") }
            false
        }
    }

    /** Best-effort system print when thermal fails (native POS only). */
    private suspend fun printSaleSystemBlocking(activity: Activity, request: SaleReceiptRequest): Boolean =
        withContext(Dispatchers.Main) {
            if (activity.isFinishing || activity.isDestroyed) return@withContext false
            try {
                val printManager = activity.getSystemService(Context.PRINT_SERVICE) as? PrintManager
                    ?: return@withContext false
                val lines = buildReceiptTextLines(request)
                val adapter = ReceiptPrintDocumentAdapter(
                    activity.applicationContext,
                    "Sale receipt",
                    lines,
                )
                printManager.print("Sale receipt", adapter, PrintAttributes.Builder().build())
                true
            } catch (e: Exception) {
                Log.e(TAG, "System print failed", e)
                showError(activity, e.message ?: "Print failed")
                false
            }
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
                saleLocalId = request.saleLocalId,
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
        SaleReceiptIds.lines(request.saleId, request.saleLocalId).forEach { lines.add(it) }
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
        lines.add("(Keep receipt for refunds)")
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
        // No thermal printer configured — fall back to the system print dialog
        // (same path sale receipts use) so the user still gets a receipt.
        printWithdrawalSystem(activity, request)
    }

    private fun printWithdrawalSystem(activity: Activity, request: WithdrawalReceiptRequest) {
        if (activity.isFinishing || activity.isDestroyed) return
        activity.runOnUiThread {
            if (activity.isFinishing || activity.isDestroyed) return@runOnUiThread
            try {
                val lines = buildWithdrawalTextLines(request)
                val printManager = activity.getSystemService(Context.PRINT_SERVICE) as? PrintManager
                    ?: run {
                        showError(activity, activity.getString(R.string.printer_none_selected))
                        return@runOnUiThread
                    }
                val adapter = ReceiptPrintDocumentAdapter(
                    activity.applicationContext,
                    "Withdrawal receipt",
                    lines,
                )
                printManager.print(
                    "Withdrawal receipt",
                    adapter,
                    PrintAttributes.Builder().build(),
                )
            } catch (e: Exception) {
                Log.e(TAG, "Withdrawal system print failed", e)
                showError(activity, e.message ?: "Print failed")
            }
        }
    }

    private fun buildWithdrawalTextLines(request: WithdrawalReceiptRequest): List<String> {
        val df = SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault())
        val lines = mutableListOf<String>()
        lines.add(request.storeName.uppercase())
        if (!request.storeLocation.isNullOrBlank()) lines.add(request.storeLocation)
        if (!request.storePhone.isNullOrBlank()) lines.add("Tel: ${request.storePhone}")
        lines.add("=".repeat(32))
        lines.add("WITHDRAWAL")
        lines.add("-".repeat(32))
        if (!request.receiptNumber.isNullOrBlank()) lines.add("Receipt #: ${request.receiptNumber}")
        if (request.withdrawalId != null) lines.add("ID: ${request.withdrawalId}")
        lines.add("Date: ${df.format(Date())}")
        if (!request.cashierName.isNullOrBlank()) lines.add("Cashier: ${request.cashierName}")
        lines.add("-".repeat(32))
        lines.add("AMOUNT: ${"%.2f".format(Locale.US, request.amount)}")
        lines.add("Reason: ${request.reason}")
        if (!request.notes.isNullOrBlank()) lines.add("Notes: ${request.notes}")
        lines.add("=".repeat(32))
        lines.add("Withdrawal receipt")
        return lines
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

/** Merge server/local ids so every printed receipt shows refund identifiers. */
fun ReceiptPrinter.SaleReceiptRequest.withSaleIds(serverSaleId: Int?, saleLocalId: Long): ReceiptPrinter.SaleReceiptRequest =
    copy(
        saleId = serverSaleId?.takeIf { it > 0 } ?: saleId,
        saleLocalId = saleLocalId.takeIf { it > 0 } ?: saleLocalId,
    )

/** Minimal receipt when only ids are available (fallback print). */
fun SaleUiEvent.Success.receiptForIdsOnly(context: Context): ReceiptPrinter.SaleReceiptRequest? {
    if (!SaleReceiptIds.hasAnyId(serverSaleId, saleLocalId)) return null
    val prefs = context.getSharedPreferences("pos", Context.MODE_PRIVATE)
    return ReceiptPrinter.SaleReceiptRequest(
        storeName = prefs.getString("store_name", context.getString(R.string.store_name))
            ?: context.getString(R.string.store_name),
        cartLines = emptyList(),
        subtotal = 0.0,
        discountTotal = 0.0,
        total = 0.0,
        payments = emptyList(),
        customerName = null,
        collectionStatus = "collected",
        cashierName = prefs.getString("username", null),
        saleId = serverSaleId,
        saleLocalId = saleLocalId.takeIf { it > 0 },
        storePhone = prefs.getString("store_phone", "") ?: "",
        storeLocation = prefs.getString("store_location", "") ?: "",
    )
}

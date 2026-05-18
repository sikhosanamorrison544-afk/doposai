package com.pos.mobile.printer

import com.pos.mobile.ui.CartLine
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class SaleReceiptLine(
    val name: String,
    val qty: Int,
    val unitPrice: Double,
    val lineTotal: Double,
)

/**
 * Builds raw ESC/POS bytes for 58mm / 80mm thermal printers (Bluetooth SPP).
 * Layout mirrors [app.escpos_printer] on the server.
 */
class EscPosReceiptBuilder(private val paperWidth: Int) {

    private val width = paperWidth.coerceIn(32, 48)
    private val buffer = ArrayList<Byte>(2048)

    fun buildSaleReceipt(
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
        footer: String = "Thank you for shopping with us!",
    ): ByteArray {
        buffer.clear()
        initPrinter()
        val lines = cartLines.map { line ->
            SaleReceiptLine(
                name = line.product.name,
                qty = line.quantity.coerceAtLeast(1),
                unitPrice = line.product.sellingPrice,
                lineTotal = line.lineTotal,
            )
        }
        return buildSaleReceiptFromLines(
            storeName, lines, subtotal, discountTotal, total, payments,
            customerName, collectionStatus, cashierName, saleId, footer,
        )
    }

    fun buildSaleReceiptFromLines(
        storeName: String,
        lines: List<SaleReceiptLine>,
        subtotal: Double,
        discountTotal: Double,
        total: Double,
        payments: List<Pair<String, Double>>,
        customerName: String?,
        collectionStatus: String,
        cashierName: String?,
        saleId: Int? = null,
        footer: String = "Thank you for shopping with us!",
    ): ByteArray {
        buffer.clear()
        initPrinter()
        writeHeader(storeName, null, null)
        writeLine('=')
        writeSaleInfo(saleId, cashierName, customerName, collectionStatus)
        writeLine('-')
        writeText("ITEMS:\n")
        for (line in lines) {
            val name = line.name.take(if (width >= 48) 30 else 22)
            writeText("$name\n")
            writeText(
                "  ${line.qty} x ${"%.2f".format(Locale.US, line.unitPrice)} = " +
                    "${"%.2f".format(Locale.US, line.lineTotal)}\n"
            )
        }
        writeLine('-')
        writeText("Subtotal:     ${"%.2f".format(Locale.US, subtotal).padStart(10)}\n")
        if (discountTotal > 0.005) {
            writeText("Discount:     ${"%.2f".format(Locale.US, discountTotal).padStart(10)}\n")
        }
        boldOn()
        writeText("TOTAL:        ${"%.2f".format(Locale.US, total).padStart(10)}\n")
        boldOff()
        writeLine('=')
        writeText("PAYMENT:\n")
        var paid = 0.0
        for ((method, amount) in payments) {
            paid += amount
            val label = formatMethod(method).take(15).padEnd(15)
            writeText("$label ${"%.2f".format(Locale.US, amount).padStart(10)}\n")
        }
        val change = paid - total
        if (change > 0.005) {
            boldOn()
            writeText("CHANGE:       ${"%.2f".format(Locale.US, change).padStart(10)}\n")
            boldOff()
        }
        writeLine('=')
        writeText("\n")
        centerAlign()
        for (line in footer.split('\n')) {
            writeWrapped(line)
        }
        leftAlign()
        finishReceipt()
        return buffer.toByteArray()
    }

    fun buildWithdrawalReceipt(
        storeName: String,
        withdrawalId: Int?,
        receiptNumber: String?,
        amount: Double,
        reason: String,
        cashierName: String?,
        notes: String?,
        storePhone: String? = null,
        storeLocation: String? = null,
    ): ByteArray {
        buffer.clear()
        initPrinter()
        writeHeader(storeName, storeLocation, storePhone)
        writeLine('=')
        writeText("\n")
        centerAlign()
        write(byteArrayOf(0x1b, 0x21, 0x18))
        writeText("WITHDRAWAL\n")
        write(byteArrayOf(0x1b, 0x21, 0x00))
        leftAlign()
        writeLine('-')
        if (!receiptNumber.isNullOrBlank()) {
            boldOn()
            writeText("Receipt #: $receiptNumber\n")
            boldOff()
        }
        if (withdrawalId != null) {
            writeText("ID: $withdrawalId\n")
        }
        writeText("Date: ${SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault()).format(Date())}\n")
        if (!cashierName.isNullOrBlank()) {
            writeText("Cashier: ${cashierName.take(width - 9)}\n")
        }
        writeLine('-')
        centerAlign()
        write(byteArrayOf(0x1b, 0x21, 0x18))
        writeText("AMOUNT: ${"%.2f".format(Locale.US, amount)}\n")
        write(byteArrayOf(0x1b, 0x21, 0x00))
        leftAlign()
        writeText("Reason: ${reason.take(width - 8)}\n")
        if (!notes.isNullOrBlank()) {
            writeText("Notes: ${notes.take(width - 7)}\n")
        }
        writeLine('=')
        centerAlign()
        writeText("Withdrawal receipt\n")
        leftAlign()
        finishReceipt()
        return buffer.toByteArray()
    }

    fun buildTestReceipt(storeName: String): ByteArray {
        buffer.clear()
        initPrinter()
        writeHeader(storeName.ifBlank { "POS" }, null, null)
        writeLine('=')
        writeText("Printer test OK\n")
        writeText(SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault()).format(Date()))
        writeText("\n")
        finishReceipt()
        return buffer.toByteArray()
    }

    private fun finishReceipt() {
        writeText("\n\n")
        write(byteArrayOf(0x1b, 0x64, 0x03))
        write(byteArrayOf(0x1d, 0x56, 0x42, 0x03))
    }

    private fun initPrinter() {
        write(byteArrayOf(0x1b, 0x40)) // ESC @
        write(byteArrayOf(0x1b, 0x21, 0x00))
    }

    private fun writeHeader(storeName: String, storeLocation: String?, storePhone: String?) {
        centerAlign()
        write(byteArrayOf(0x1b, 0x21, 0x08)) // bold
        writeText("${storeName.uppercase()}\n")
        write(byteArrayOf(0x1b, 0x21, 0x00))
        if (!storeLocation.isNullOrBlank()) {
            writeText("${storeLocation.take(width)}\n")
        }
        if (!storePhone.isNullOrBlank()) {
            writeText("Tel: ${storePhone.take(width - 5)}\n")
        }
        leftAlign()
    }

    companion object {
        fun parseSaleJson(json: JSONObject, paperWidth: Int = PrinterPreferences.DEFAULT_PAPER_WIDTH): ByteArray {
            val store = json.optJSONObject("store")
            val storeName = store?.optString("store_name")?.takeIf { it.isNotBlank() }
                ?: json.optString("storeName", "POS")
            val builder = EscPosReceiptBuilder(
                json.optInt("paperWidth", paperWidth).coerceIn(32, 48),
            )
            val items = json.optJSONArray("items") ?: JSONArray()
            val lines = mutableListOf<SaleReceiptLine>()
            for (i in 0 until items.length()) {
                val item = items.getJSONObject(i)
                val qty = item.optDouble("qty", item.optDouble("quantity", 1.0)).toInt().coerceAtLeast(1)
                val unit = item.optDouble("unit_price", item.optDouble("unitPrice", 0.0))
                val lineTotal = item.optDouble("line_total", item.optDouble("lineTotal", unit * qty))
                lines.add(
                    SaleReceiptLine(
                        name = item.optString("name", "Item"),
                        qty = qty,
                        unitPrice = unit,
                        lineTotal = lineTotal,
                    )
                )
            }
            val paymentsArr = json.optJSONArray("payments") ?: JSONArray()
            val payments = mutableListOf<Pair<String, Double>>()
            for (i in 0 until paymentsArr.length()) {
                val p = paymentsArr.getJSONObject(i)
                payments.add(p.optString("method", "cash") to p.optDouble("amount", 0.0))
            }
            val saleId = if (json.has("saleId")) json.optInt("saleId") else null
            return builder.buildSaleReceiptFromLines(
                storeName = storeName,
                lines = lines,
                subtotal = json.optDouble("subtotal", 0.0),
                discountTotal = json.optDouble("discountTotal", json.optDouble("discount_total", 0.0)),
                total = json.optDouble("total", 0.0),
                payments = payments,
                customerName = json.optString("customerName", json.optString("customer_name", null)),
                collectionStatus = json.optString("collectionStatus", json.optString("collection_status", "collected")),
                cashierName = json.optString("cashierName", json.optString("cashier_name", null)),
                saleId = saleId,
            )
        }

        fun parseWithdrawalJson(json: JSONObject, paperWidth: Int = PrinterPreferences.DEFAULT_PAPER_WIDTH): ByteArray {
            val store = json.optJSONObject("store")
            val storeName = store?.optString("store_name")?.takeIf { it.isNotBlank() }
                ?: json.optString("storeName", "POS")
            val builder = EscPosReceiptBuilder(
                json.optInt("paperWidth", paperWidth).coerceIn(32, 48),
            )
            val withdrawalId = if (json.has("withdrawalId")) json.optInt("withdrawalId") else null
            return builder.buildWithdrawalReceipt(
                storeName = storeName,
                withdrawalId = withdrawalId,
                receiptNumber = json.optString("receiptNumber", json.optString("receipt_number", null)),
                amount = json.optDouble("amount", 0.0),
                reason = json.optString("reason", ""),
                cashierName = json.optString("cashierName", json.optString("cashier_name", null)),
                notes = json.optString("notes", null),
                storePhone = store?.optString("store_phone"),
                storeLocation = store?.optString("store_location"),
            )
        }
    }

    private fun writeSaleInfo(
        saleId: Int?,
        cashierName: String?,
        customerName: String?,
        collectionStatus: String,
    ) {
        val df = SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault())
        if (saleId != null) {
            writeText("Sale #: $saleId\n")
        }
        writeText("Date:   ${df.format(Date())}\n")
        if (!cashierName.isNullOrBlank()) {
            writeText("Cashier: ${cashierName.take(width - 9)}\n")
        }
        if (!customerName.isNullOrBlank()) {
            writeText("Customer: ${customerName.take(width - 10)}\n")
        }
        boldOn()
        if (collectionStatus == "to_collect") {
            writeText("STATUS: COLLECTION PENDING\n")
        } else {
            writeText("STATUS: COLLECTED\n")
        }
        boldOff()
    }

    private fun writeLine(char: Char) {
        writeText(char.toString().repeat(width) + "\n")
    }

    private fun writeWrapped(text: String) {
        if (text.length <= width) {
            writeText("$text\n")
            return
        }
        val words = text.split(' ')
        var current = ""
        for (word in words) {
            val next = if (current.isEmpty()) word else "$current $word"
            if (next.length <= width) {
                current = next
            } else {
                if (current.isNotEmpty()) writeText("$current\n")
                current = word
            }
        }
        if (current.isNotEmpty()) writeText("$current\n")
    }

    private fun centerAlign() = write(byteArrayOf(0x1b, 0x61, 0x01))
    private fun leftAlign() = write(byteArrayOf(0x1b, 0x61, 0x00))
    private fun boldOn() = write(byteArrayOf(0x1b, 0x45, 0x01))
    private fun boldOff() = write(byteArrayOf(0x1b, 0x45, 0x00))

    private fun writeText(text: String) {
        val bytes = text.toByteArray(Charsets.US_ASCII)
        write(bytes)
    }

    private fun write(data: ByteArray) {
        buffer.addAll(data.toList())
    }

    private fun formatMethod(method: String): String = when (method) {
        "cash" -> "Cash"
        "mobile_money" -> "Mobile Money"
        "card" -> "Card"
        "credit" -> "Credit"
        else -> method.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }
}

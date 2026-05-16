package com.pos.mobile.ui

import android.content.Context
import android.print.PrintAttributes
import android.print.PrintManager
import android.webkit.WebView
import android.webkit.WebViewClient
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object ReceiptPrinter {

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
    ) {
        val html = buildSaleHtml(
            storeName = storeName,
            cartLines = cartLines,
            subtotal = subtotal,
            discountTotal = discountTotal,
            total = total,
            payments = payments,
            customerName = customerName,
            collectionStatus = collectionStatus,
            cashierName = cashierName,
        )
        printHtml(context, html, "Sale receipt")
    }

    private fun buildSaleHtml(
        storeName: String,
        cartLines: List<CartLine>,
        subtotal: Double,
        discountTotal: Double,
        total: Double,
        payments: List<Pair<String, Double>>,
        customerName: String?,
        collectionStatus: String,
        cashierName: String?,
    ): String {
        val df = SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault())
        val sb = StringBuilder()
        sb.append("<html><head><meta charset='utf-8'><style>")
        sb.append("body{font-family:monospace;font-size:12px;margin:8px;max-width:280px}")
        sb.append(".store{text-align:center;font-weight:bold;font-size:14px}")
        sb.append("hr{border:none;border-top:1px dashed #000;margin:6px 0}")
        sb.append("table{width:100%} td{padding:2px 0}")
        sb.append(".total{font-weight:bold}</style></head><body>")
        sb.append("<div class='store'>").append(escape(storeName.uppercase())).append("</div>")
        sb.append("<hr><div>Date: ").append(df.format(Date())).append("</div>")
        if (!cashierName.isNullOrBlank()) {
            sb.append("<div>Cashier: ").append(escape(cashierName)).append("</div>")
        }
        if (!customerName.isNullOrBlank()) {
            sb.append("<div>Customer: ").append(escape(customerName)).append("</div>")
        }
        if (collectionStatus == "to_collect") {
            sb.append("<div><b>STATUS: COLLECTION PENDING</b></div>")
        } else {
            sb.append("<div><b>STATUS: COLLECTED</b></div>")
        }
        sb.append("<hr><b>ITEMS:</b><table>")
        for (line in cartLines) {
            val qty = line.quantity.coerceAtLeast(1)
            sb.append("<tr><td colspan='2'><b>").append(escape(line.product.name)).append("</b></td></tr>")
            sb.append("<tr><td>").append(qty).append(" x ")
                .append(String.format(Locale.US, "%.2f", line.product.sellingPrice))
                .append("</td><td align='right'>")
                .append(String.format(Locale.US, "%.2f", line.lineTotal))
                .append("</td></tr>")
        }
        sb.append("</table><hr><table>")
        sb.append("<tr><td>Subtotal:</td><td align='right'>")
            .append(String.format(Locale.US, "%.2f", subtotal)).append("</td></tr>")
        if (discountTotal > 0) {
            sb.append("<tr><td>Discount:</td><td align='right'>")
                .append(String.format(Locale.US, "%.2f", discountTotal)).append("</td></tr>")
        }
        sb.append("<tr class='total'><td>TOTAL:</td><td align='right'>")
            .append(String.format(Locale.US, "%.2f", total)).append("</td></tr>")
        sb.append("</table><hr><b>PAYMENT:</b><table>")
        var paid = 0.0
        for ((method, amount) in payments) {
            paid += amount
            sb.append("<tr><td>").append(escape(formatMethod(method)))
                .append("</td><td align='right'>")
                .append(String.format(Locale.US, "%.2f", amount))
                .append("</td></tr>")
        }
        val change = paid - total
        if (change > 0.005) {
            sb.append("<tr class='total'><td>CHANGE:</td><td align='right'>")
                .append(String.format(Locale.US, "%.2f", change))
                .append("</td></tr>")
        }
        sb.append("</table><hr><div style='text-align:center'>Thank you!</div></body></html>")
        return sb.toString()
    }

    private fun formatMethod(method: String): String = when (method) {
        "cash" -> "Cash"
        "mobile_money" -> "Mobile Money"
        "card" -> "Card"
        "credit" -> "Credit"
        else -> method.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }

    private fun escape(s: String): String =
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    private fun printHtml(context: Context, html: String, jobName: String) {
        val webView = WebView(context)
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                val printManager = context.getSystemService(Context.PRINT_SERVICE) as PrintManager
                val adapter = view?.createPrintDocumentAdapter(jobName)
                if (adapter != null) {
                    printManager.print(
                        jobName,
                        adapter,
                        PrintAttributes.Builder().build()
                    )
                }
            }
        }
        webView.loadDataWithBaseURL(null, html, "text/HTML", "UTF-8", null)
    }
}

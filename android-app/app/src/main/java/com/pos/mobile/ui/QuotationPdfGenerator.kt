package com.pos.mobile.ui

import android.content.Context
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.TextPaint
import org.json.JSONObject
import java.io.File
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Builds a quotation PDF on-device when the server is unreachable (offline-first).
 * Layout mirrors the server PDF: shop header, cashier, compact product table.
 */
object QuotationPdfGenerator {

    private const val PRODUCT_NAME_MAX = 40
    private const val PAGE_W = 595
    private const val PAGE_H = 842
    private const val MARGIN = 42f

    data class Request(
        val storeName: String,
        val storePhone: String?,
        val storeLocation: String?,
        val quotationNumber: String,
        val customerName: String,
        val cashierName: String?,
        val cartLines: List<CartLine>,
        val subtotal: Double,
        val discountTotal: Double,
        val total: Double,
        val createdAt: Date = Date(),
    )

    fun loadStoreFromPrefs(context: Context): Triple<String, String?, String?> {
        val json = PosAuth.prefs(context).getString("store_settings_json", null)
            ?: return Triple(context.getString(com.pos.mobile.R.string.store_name), null, null)
        return try {
            val o = JSONObject(json)
            Triple(
                o.optString("store_name", "Store").ifBlank { "Store" },
                o.optString("store_phone").takeIf { it.isNotBlank() },
                o.optString("store_location").takeIf { it.isNotBlank() },
            )
        } catch (_: Exception) {
            Triple("Store", null, null)
        }
    }

    fun offlineQuotationNumber(): String {
        val fmt = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US)
        return "Q-${fmt.format(Date())}"
    }

    fun shortProductName(name: String, maxChars: Int = PRODUCT_NAME_MAX): String {
        val text = name.trim().replace(Regex("\\s+"), " ")
        if (text.isEmpty()) return "—"
        if (text.length <= maxChars) return text
        return text.take(maxChars - 1).trimEnd() + "…"
    }

    fun generate(context: Context, request: Request): File {
        val dir = File(context.cacheDir, "quotations").apply { mkdirs() }
        val safeName = request.quotationNumber.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val out = File(dir, "$safeName.pdf")

        val currency = NumberFormat.getCurrencyInstance(Locale.US)
        val dateFmt = SimpleDateFormat("dd MMM yyyy", Locale.US)

        val titlePaint = TextPaint().apply {
            textSize = 16f
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            color = 0xFF1E3A8A.toInt()
            isAntiAlias = true
        }
        val subPaint = TextPaint().apply {
            textSize = 9f
            color = 0xFF4B5563.toInt()
            isAntiAlias = true
        }
        val headingPaint = TextPaint().apply {
            textSize = 13f
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            color = 0xFF1E3A8A.toInt()
            isAntiAlias = true
        }
        val bodyPaint = TextPaint().apply {
            textSize = 9f
            color = 0xFF111827.toInt()
            isAntiAlias = true
        }
        val labelPaint = TextPaint().apply {
            textSize = 8f
            color = 0xFF6B7280.toInt()
            isAntiAlias = true
        }
        val headerRowPaint = TextPaint().apply {
            textSize = 8f
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            color = 0xFFFFFFFF.toInt()
            isAntiAlias = true
        }
        val rowPaint = TextPaint().apply {
            textSize = 8f
            color = 0xFF111827.toInt()
            isAntiAlias = true
        }
        val totalPaint = TextPaint().apply {
            textSize = 11f
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            color = 0xFF1E3A8A.toInt()
            isAntiAlias = true
        }
        val footerPaint = TextPaint().apply {
            textSize = 8f
            color = 0xFF9CA3AF.toInt()
            isAntiAlias = true
        }
        val linePaint = Paint().apply {
            color = 0xFFE5E7EB.toInt()
            strokeWidth = 1f
        }
        val headerBg = Paint().apply { color = 0xFF1E3A8A.toInt() }
        val zebraLight = Paint().apply { color = 0xFFF8FAFC.toInt() }

        val document = PdfDocument()
        var pageNum = 1
        var page = document.startPage(PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, pageNum).create())
        var canvas = page.canvas
        var y = MARGIN

        fun newPageIfNeeded(need: Float) {
            if (y + need <= PAGE_H - MARGIN) return
            document.finishPage(page)
            pageNum++
            page = document.startPage(PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, pageNum).create())
            canvas = page.canvas
            y = MARGIN
        }

        fun drawCentered(text: String, paint: TextPaint) {
            val w = paint.measureText(text)
            canvas.drawText(text, (PAGE_W - w) / 2f, y, paint)
            y += paint.textSize + 6f
        }

        fun drawLine(left: String, right: String) {
            canvas.drawText(left, MARGIN, y, labelPaint)
            canvas.drawText(right, MARGIN + 200f, y, bodyPaint)
            y += 12f
        }

        drawCentered(request.storeName, titlePaint)
        val contact = buildList {
            request.storeLocation?.let { add(it.replace("\n", ", ")) }
            request.storePhone?.let { add("Tel: $it") }
        }.joinToString(" · ")
        if (contact.isNotBlank()) {
            drawCentered(contact, subPaint)
        }
        y += 4f
        drawCentered("QUOTATION", headingPaint)
        canvas.drawLine(MARGIN, y, PAGE_W - MARGIN, y, linePaint)
        y += 14f

        drawLine("Quotation No.", request.quotationNumber)
        drawLine("Date", dateFmt.format(request.createdAt))
        drawLine("Valid Until", "30 days from date")
        drawLine("Cashier", request.cashierName?.takeIf { it.isNotBlank() } ?: "—")
        drawLine("Customer", request.customerName)
        drawLine("Status", "DRAFT")
        y += 8f

        val colX = floatArrayOf(MARGIN, MARGIN + 22f, MARGIN + 200f, MARGIN + 320f, MARGIN + 390f, MARGIN + 450f)
        val rowH = 16f
        val headers = arrayOf("#", "Product", "Qty", "Unit", "Disc.", "Total")

        newPageIfNeeded(rowH * (request.cartLines.size + 3))
        canvas.drawRect(MARGIN, y - 10f, PAGE_W - MARGIN, y + rowH - 6f, headerBg)
        headers.forEachIndexed { i, h ->
            val alignX = when (i) {
                0 -> colX[i]
                1 -> colX[i]
                else -> colX[i]
            }
            canvas.drawText(h, alignX, y, headerRowPaint)
        }
        y += rowH

        request.cartLines.forEachIndexed { index, line ->
            newPageIfNeeded(rowH + 4f)
            if (index % 2 == 1) {
                canvas.drawRect(MARGIN, y - 10f, PAGE_W - MARGIN, y + rowH - 6f, zebraLight)
            }
            val row = arrayOf(
                "${index + 1}",
                shortProductName(line.product.name),
                "${line.quantity}",
                currency.format(line.product.sellingPrice),
                currency.format(line.discount),
                currency.format(line.lineTotal),
            )
            row.forEachIndexed { i, cell ->
                val paint = rowPaint
                val x = when (i) {
                    0 -> colX[i]
                    1 -> colX[i]
                    else -> colX[i]
                }
                canvas.drawText(cell, x, y, paint)
            }
            y += rowH
        }

        y += 10f
        newPageIfNeeded(60f)
        val totalsX = PAGE_W - MARGIN - 160f
        canvas.drawText("Subtotal", totalsX, y, bodyPaint)
        canvas.drawText(currency.format(request.subtotal), totalsX + 90f, y, bodyPaint)
        y += 14f
        canvas.drawText("Discount", totalsX, y, bodyPaint)
        canvas.drawText(currency.format(request.discountTotal), totalsX + 90f, y, bodyPaint)
        y += 14f
        canvas.drawLine(totalsX, y, PAGE_W - MARGIN, y, linePaint)
        y += 12f
        canvas.drawText("TOTAL", totalsX, y, totalPaint)
        canvas.drawText(currency.format(request.total), totalsX + 90f, y, totalPaint)
        y += 24f

        val footer = "Prices are subject to confirmation. Thank you for your business."
        val fw = footerPaint.measureText(footer)
        canvas.drawText(footer, (PAGE_W - fw) / 2f, y, footerPaint)

        document.finishPage(page)
        out.outputStream().use { document.writeTo(it) }
        document.close()
        return out
    }
}

package com.pos.mobile.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.print.pdf.PrintedPdfDocument
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.print.PageRange
import android.print.PrintAttributes
import android.print.PrintDocumentAdapter
import android.print.PrintDocumentInfo

/**
 * System print (share/PDF) without WebView — avoids WebView crashes on many POS devices.
 */
class ReceiptPrintDocumentAdapter(
    private val context: Context,
    private val jobName: String,
    private val lines: List<String>,
) : PrintDocumentAdapter() {

    private var pdf: PrintedPdfDocument? = null
    private var pageWidth = 0
    private var pageHeight = 0

    override fun onLayout(
        oldAttributes: PrintAttributes?,
        newAttributes: PrintAttributes,
        cancellationSignal: CancellationSignal,
        callback: LayoutResultCallback,
        extras: Bundle?,
    ) {
        if (cancellationSignal.isCanceled) {
            callback.onLayoutCancelled()
            return
        }
        pdf = PrintedPdfDocument(context, newAttributes)
        val mediaSize = newAttributes.mediaSize ?: PrintAttributes.MediaSize.ISO_A4
        pageWidth = (mediaSize.widthMils / 1000.0 * 72).toInt()
        pageHeight = (lines.size * LINE_HEIGHT_PT + PAGE_PADDING_PT * 2).coerceIn(200, 11 * 72)
        val info = PrintDocumentInfo.Builder(jobName)
            .setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT)
            .setPageCount(1)
            .build()
        callback.onLayoutFinished(info, true)
    }

    override fun onWrite(
        pages: Array<out PageRange>,
        destination: ParcelFileDescriptor,
        cancellationSignal: CancellationSignal,
        callback: WriteResultCallback,
    ) {
        val document = pdf
        if (document == null) {
            callback.onWriteFailed("Layout not ready")
            return
        }
        if (cancellationSignal.isCanceled) {
            callback.onWriteCancelled()
            return
        }
        try {
            val page = document.startPage(0)
            drawLines(page.canvas)
            document.finishPage(page)
            document.writeTo(ParcelFileDescriptor.AutoCloseOutputStream(destination))
            callback.onWriteFinished(arrayOf(PageRange.ALL_PAGES))
        } catch (e: Exception) {
            callback.onWriteFailed(e.message)
        } finally {
            document.close()
            pdf = null
        }
    }

    private fun drawLines(canvas: Canvas) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            typeface = Typeface.MONOSPACE
            textSize = 10f
        }
        var y = PAGE_PADDING_PT.toFloat()
        for (line in lines) {
            canvas.drawText(line, PAGE_PADDING_PT.toFloat(), y, paint)
            y += LINE_HEIGHT_PT
        }
    }

    companion object {
        private const val LINE_HEIGHT_PT = 14
        private const val PAGE_PADDING_PT = 24
    }
}

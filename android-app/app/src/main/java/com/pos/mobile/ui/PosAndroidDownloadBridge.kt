package com.pos.mobile.ui

import android.content.ContentValues
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.webkit.JavascriptInterface
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.io.IOException

/**
 * Saves PDF bytes from the WebView (price list export) into the user's Downloads folder.
 */
class PosAndroidDownloadBridge(
    private val activity: AppCompatActivity,
) {
    @JavascriptInterface
    fun savePdf(base64Data: String, filename: String): String {
        return try {
            val bytes = Base64.decode(base64Data, Base64.DEFAULT)
            if (bytes.isEmpty()) {
                return errorJson("Empty PDF data")
            }
            val safeName = sanitizeFilename(filename.ifBlank { "price_list.pdf" })
            val uri = writeToDownloads(safeName, bytes)
            JSONObject()
                .put("ok", true)
                .put("filename", safeName)
                .put("uri", uri.toString())
                .toString()
        } catch (e: Exception) {
            errorJson(e.message ?: "Save failed")
        }
    }

    private fun writeToDownloads(filename: String, bytes: ByteArray): android.net.Uri {
        val resolver = activity.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, filename)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/pdf")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
        }
        val collection = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            MediaStore.Downloads.EXTERNAL_CONTENT_URI
        } else {
            @Suppress("DEPRECATION")
            MediaStore.Files.getContentUri("external")
        }
        val uri = resolver.insert(collection, values)
            ?: throw IOException("Could not create download file")
        resolver.openOutputStream(uri)?.use { out ->
            out.write(bytes)
            out.flush()
        } ?: throw IOException("Could not open output stream")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val done = ContentValues().apply {
                put(MediaStore.MediaColumns.IS_PENDING, 0)
            }
            resolver.update(uri, done, null, null)
        }
        return uri
    }

    private fun sanitizeFilename(name: String): String {
        val trimmed = name.trim().ifBlank { "price_list.pdf" }
        val withExt = if (trimmed.lowercase().endsWith(".pdf")) trimmed else "$trimmed.pdf"
        return withExt.replace(Regex("[\\\\/:*?\"<>|]"), "_")
    }

    private fun errorJson(message: String): String =
        JSONObject().put("ok", false).put("error", message).toString()
}

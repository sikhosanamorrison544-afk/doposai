package com.pos.mobile.ui

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.JavascriptInterface
import androidx.appcompat.app.AppCompatActivity
import com.pos.mobile.BuildConfig
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okio.source
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Reads inventory import files picked in WebView (content:// URIs) and uploads them
 * via multipart POST. WebView often leaves &lt;input type="file"&gt; without a usable FileList.
 */
class PosAndroidImportBridge(
    private val activity: AppCompatActivity,
) {
    @Volatile
    private var pendingUri: Uri? = null

    @Volatile
    private var pendingFileName: String? = null

    private val http = OkHttpClient.Builder()
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    fun setPendingImport(uri: Uri?, fileName: String?) {
        pendingUri = uri
        pendingFileName = fileName
    }

    fun resolveDisplayName(uri: Uri): String {
        if (uri.scheme == "content") {
            activity.contentResolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0) {
                        val name = cursor.getString(idx)?.trim()
                        if (!name.isNullOrEmpty()) return name
                    }
                }
            }
        }
        val segment = uri.lastPathSegment?.substringAfterLast('/')?.trim()
        return if (!segment.isNullOrEmpty()) segment else "import.csv"
    }

    @JavascriptInterface
    fun hasPendingImport(): Boolean = pendingUri != null

    @JavascriptInterface
    fun getPendingImportName(): String = pendingFileName ?: ""

    @JavascriptInterface
    fun clearPendingImport() {
        pendingUri = null
        pendingFileName = null
    }

    @JavascriptInterface
    fun uploadPendingImport(): String {
        val uri = pendingUri
            ?: return errorJson("No file selected. Choose a CSV file again.")
        val prefs = activity.getSharedPreferences("pos", Context.MODE_PRIVATE)
        val token = prefs.getString("token", null)?.trim()
        if (token.isNullOrEmpty()) {
            return errorJson("Not signed in. Open Admin from the app after logging in.")
        }
        val baseUrl = (
            prefs.getString("base_url", BuildConfig.DEFAULT_API_BASE_URL)
                ?: BuildConfig.DEFAULT_API_BASE_URL
            ).trimEnd('/')
        val fileName = pendingFileName ?: resolveDisplayName(uri)
        val mime = activity.contentResolver.getType(uri) ?: guessMime(fileName)

        return try {
            val fileBody = object : okhttp3.RequestBody() {
                override fun contentType() = mime.toMediaTypeOrNull()

                override fun contentLength(): Long {
                    activity.contentResolver.openAssetFileDescriptor(uri, "r")?.use { afd ->
                        if (afd.length >= 0) return afd.length
                    }
                    return -1
                }

                override fun writeTo(sink: okio.BufferedSink) {
                    activity.contentResolver.openInputStream(uri)?.use { input ->
                        sink.writeAll(input.source())
                    } ?: throw IllegalStateException("Cannot read selected file")
                }
            }

            val multipart = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", fileName, fileBody)
                .build()

            val request = Request.Builder()
                .url("$baseUrl/api/products/import")
                .addHeader("Authorization", "Bearer $token")
                .post(multipart)
                .build()

            http.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    return errorJson(parseApiError(body, response.code))
                }
                clearPendingImport()
                JSONObject().apply {
                    put("ok", true)
                    try {
                        put("result", JSONObject(body))
                    } catch (_: Exception) {
                        put("result", JSONObject().put("raw", body))
                    }
                }.toString()
            }
        } catch (e: Exception) {
            errorJson(e.message ?: "Import failed")
        }
    }

    private fun guessMime(fileName: String): String {
        val lower = fileName.lowercase()
        return when {
            lower.endsWith(".csv") -> "text/csv"
            lower.endsWith(".pdf") -> "application/pdf"
            lower.endsWith(".docx") ->
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            lower.endsWith(".doc") -> "application/msword"
            else -> "application/octet-stream"
        }
    }

    private fun parseApiError(body: String, code: Int): String {
        if (body.isBlank()) return "Upload failed (HTTP $code)"
        return try {
            val j = JSONObject(body)
            when (val detail = j.opt("detail")) {
                is String -> detail
                else -> body.take(400)
            }
        } catch (_: Exception) {
            body.take(400)
        }
    }

    private fun errorJson(message: String): String =
        JSONObject().put("ok", false).put("error", message).toString()
}

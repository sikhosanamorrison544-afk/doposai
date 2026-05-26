package com.pos.mobile.printer

import android.annotation.SuppressLint
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.pos.mobile.ui.PosAndroidDownloadBridge
import com.pos.mobile.ui.PosAndroidImportBridge
import com.pos.mobile.ui.PosAndroidOfflineBridge
import com.pos.mobile.ui.PosAndroidSettingsBridge
import com.pos.mobile.ui.PosAndroidUiBridge

object WebViewPrintSupport {

    @SuppressLint("SetJavaScriptEnabled")
    fun attach(
        activity: AppCompatActivity,
        webView: WebView,
        importBridge: PosAndroidImportBridge,
    ) {
        webView.settings.javaScriptEnabled = true
        webView.addJavascriptInterface(
            PosAndroidPrintBridge(activity, activity.lifecycleScope),
            "PosAndroidPrint",
        )
        webView.addJavascriptInterface(
            PosAndroidUiBridge(activity),
            "PosAndroidUi",
        )
        webView.addJavascriptInterface(importBridge, "PosAndroidImport")
        webView.addJavascriptInterface(
            PosAndroidOfflineBridge(activity.applicationContext),
            "PosAndroidOffline",
        )
        webView.addJavascriptInterface(
            PosAndroidSettingsBridge(activity.applicationContext),
            "PosAndroidSettings",
        )
        webView.addJavascriptInterface(
            PosAndroidDownloadBridge(activity),
            "PosAndroidDownload",
        )
    }

    const val INJECT_FLAG = "pos_android_print_injected"

    fun injectHelper(webView: WebView) {
        val script = """
            (function() {
                if (window.__posAndroidPrintReady) return;
                window.__posAndroidPrintReady = true;
                window.posNativeImport = {
                    hasPending: function() {
                        try {
                            if (typeof PosAndroidImport === 'undefined') return false;
                            return PosAndroidImport.hasPendingImport() === true;
                        } catch (e) { return false; }
                    },
                    upload: function() {
                        try {
                            if (typeof PosAndroidImport === 'undefined') {
                                return { ok: false, error: 'Import not available' };
                            }
                            return JSON.parse(PosAndroidImport.uploadPendingImport());
                        } catch (e) {
                            return { ok: false, error: String(e) };
                        }
                    }
                };
                window.posNativePrint = {
                    isAvailable: function() {
                        try {
                            if (typeof PosAndroidPrint === 'undefined') return { native: false };
                            return JSON.parse(PosAndroidPrint.isAvailable());
                        } catch (e) { return { native: false }; }
                    },
                    printSale: function(opts, transport) {
                        try {
                            if (typeof PosAndroidPrint === 'undefined') return { ok: false };
                            var t = transport ? String(transport) : '';
                            return JSON.parse(PosAndroidPrint.printSaleReceipt(JSON.stringify(opts || {}), t));
                        } catch (e) { return { ok: false, error: String(e) }; }
                    },
                    printWithdrawal: function(opts, transport) {
                        try {
                            if (typeof PosAndroidPrint === 'undefined') return { ok: false };
                            var t = transport ? String(transport) : '';
                            return JSON.parse(PosAndroidPrint.printWithdrawalReceipt(JSON.stringify(opts || {}), t));
                        } catch (e) { return { ok: false, error: String(e) }; }
                    }
                };
                window.posNativeDownload = {
                    savePdf: function(base64, filename) {
                        try {
                            if (typeof PosAndroidDownload === 'undefined') {
                                return { ok: false, error: 'Download not available' };
                            }
                            return JSON.parse(PosAndroidDownload.savePdf(base64, filename || 'price_list.pdf'));
                        } catch (e) {
                            return { ok: false, error: String(e) };
                        }
                    }
                };
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }
}

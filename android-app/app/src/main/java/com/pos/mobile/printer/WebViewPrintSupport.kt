package com.pos.mobile.printer

import android.annotation.SuppressLint
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.pos.mobile.ui.PosAndroidUiBridge

object WebViewPrintSupport {

    @SuppressLint("SetJavaScriptEnabled")
    fun attach(activity: AppCompatActivity, webView: WebView) {
        webView.settings.javaScriptEnabled = true
        webView.addJavascriptInterface(
            PosAndroidPrintBridge(activity, activity.lifecycleScope),
            "PosAndroidPrint",
        )
        webView.addJavascriptInterface(
            PosAndroidUiBridge(activity),
            "PosAndroidUi",
        )
    }

    const val INJECT_FLAG = "pos_android_print_injected"

    fun injectHelper(webView: WebView) {
        val script = """
            (function() {
                if (window.__posAndroidPrintReady) return;
                window.__posAndroidPrintReady = true;
                window.posNativePrint = {
                    isAvailable: function() {
                        try {
                            if (typeof PosAndroidPrint === 'undefined') return { native: false };
                            return JSON.parse(PosAndroidPrint.isAvailable());
                        } catch (e) { return { native: false }; }
                    },
                    printSale: function(opts) {
                        try {
                            if (typeof PosAndroidPrint === 'undefined') return { ok: false };
                            return JSON.parse(PosAndroidPrint.printSaleReceipt(JSON.stringify(opts || {})));
                        } catch (e) { return { ok: false, error: String(e) }; }
                    },
                    printWithdrawal: function(opts) {
                        try {
                            if (typeof PosAndroidPrint === 'undefined') return { ok: false };
                            return JSON.parse(PosAndroidPrint.printWithdrawalReceipt(JSON.stringify(opts || {})));
                        } catch (e) { return { ok: false, error: String(e) }; }
                    }
                };
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }
}

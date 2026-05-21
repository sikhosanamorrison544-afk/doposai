package com.pos.mobile.ui

import android.content.Context
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.appbar.MaterialToolbar
import com.pos.mobile.R
import java.text.NumberFormat
import java.util.Locale

object NativeUi {

    val currencyFormat: NumberFormat = NumberFormat.getCurrencyInstance(Locale.US)

    fun formatMoney(amount: Double): String = currencyFormat.format(amount)

    fun showError(context: Context, message: String) {
        Toast.makeText(context, message, Toast.LENGTH_LONG).show()
    }

    fun showSuccess(context: Context, message: String) {
        Toast.makeText(context, message, Toast.LENGTH_LONG).show()
    }

    fun bindMessage(tv: TextView, message: String?, isError: Boolean = true) {
        if (message.isNullOrBlank()) {
            tv.visibility = View.GONE
            return
        }
        tv.text = message
        tv.setTextColor(
            tv.context.getColor(if (isError) R.color.danger else R.color.success),
        )
        tv.visibility = View.VISIBLE
    }
}

abstract class BaseNativeActivity : AppCompatActivity() {

    protected fun attachNativeScreen(title: String, contentLayoutRes: Int): android.view.View {
        setContentView(R.layout.activity_native_shell)
        setupToolbar(title)
        val root = findViewById<android.widget.FrameLayout>(R.id.native_content)
        return layoutInflater.inflate(contentLayoutRes, root, true)
    }

    protected fun setupToolbar(title: String) {
        val toolbar = findViewById<MaterialToolbar>(R.id.native_toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.title = title
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }

    /** Resume a deferred Bluetooth print after the user grants runtime permission. */
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == com.pos.mobile.printer.PrinterPermissionHelper.REQUEST_CODE) {
            val prefs = getSharedPreferences("pos", MODE_PRIVATE)
            val storeName = prefs.getString("store_name", getString(R.string.store_name))
                ?: getString(R.string.store_name)
            val granted = com.pos.mobile.printer.PrinterPermissionHelper
                .legacyResultsGranted(permissions, grantResults)
            com.pos.mobile.printer.PrinterSetupDialog.handleBluetoothPermissionResult(
                activity = this,
                granted = granted,
                scope = lifecycleScope,
                storeName = storeName,
            )
        }
    }
}

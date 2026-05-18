package com.pos.mobile.printer

import android.content.Context
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.pos.mobile.R
import java.util.WeakHashMap

/** Modern runtime permission flow for Bluetooth printer (Android 12+). */
class BluetoothPermissionDelegate private constructor(private val activity: AppCompatActivity) {

    companion object {
        private val byActivity = WeakHashMap<AppCompatActivity, BluetoothPermissionDelegate>()

        fun install(activity: AppCompatActivity): BluetoothPermissionDelegate =
            byActivity.getOrPut(activity) { BluetoothPermissionDelegate(activity) }

        fun get(activity: AppCompatActivity): BluetoothPermissionDelegate? = byActivity[activity]
    }

    private val launcher = activity.registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { results ->
        val granted = PrinterPermissionHelper.evaluateResults(activity, results)
        val storeName = activity.getSharedPreferences("pos", Context.MODE_PRIVATE)
            .getString("store_name", activity.getString(R.string.store_name))
            ?: activity.getString(R.string.store_name)
        PrinterSetupDialog.handleBluetoothPermissionResult(
            activity = activity,
            granted = granted,
            scope = activity.lifecycleScope,
            storeName = storeName,
        )
    }

    fun request() {
        val missing = PrinterPermissionHelper.missingPermissions(activity)
        if (missing.isNotEmpty()) {
            launcher.launch(missing)
        }
    }
}

val AppCompatActivity.bluetoothPermissionDelegate: BluetoothPermissionDelegate?
    get() = BluetoothPermissionDelegate.get(this)

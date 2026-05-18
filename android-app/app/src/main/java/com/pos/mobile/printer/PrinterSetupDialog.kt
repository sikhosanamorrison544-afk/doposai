package com.pos.mobile.printer

import android.Manifest
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.usb.UsbDevice
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.pos.mobile.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

object PrinterSetupDialog {

    /** @deprecated use [PrinterPermissionHelper.REQUEST_CODE] */
    const val REQUEST_BLUETOOTH_PRINTER = PrinterPermissionHelper.REQUEST_CODE

    private var pendingBluetoothAction: (() -> Unit)? = null

    fun hasBluetoothPermissions(activity: Activity): Boolean =
        PrinterPermissionHelper.hasAll(activity)

    fun requestBluetoothPermissions(activity: Activity, requestCode: Int) {
        ActivityCompat.requestPermissions(activity, PrinterPermissionHelper.requiredPermissions(), requestCode)
    }

    /**
     * Runs [action] when Bluetooth permission is granted (Android 12+).
     * Otherwise shows the system permission dialog and runs [action] after the user allows it.
     */
    /** Request Bluetooth permission if needed, then run [action]. Used for test print and sale receipts. */
    fun runWithBluetoothPermission(activity: AppCompatActivity, action: () -> Unit) {
        withBluetoothPermission(activity, action)
    }

    private fun withBluetoothPermission(activity: AppCompatActivity, action: () -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || hasBluetoothPermissions(activity)) {
            action()
            return
        }
        pendingBluetoothAction = action
        PrinterPermissionHelper.request(activity)
        Toast.makeText(activity, R.string.printer_permission_needed, Toast.LENGTH_LONG).show()
    }

    fun handleBluetoothPermissionResult(
        activity: AppCompatActivity,
        @Suppress("UNUSED_PARAMETER") granted: Boolean,
        scope: CoroutineScope,
        storeName: String,
    ) {
        if (PrinterPermissionHelper.hasAll(activity)) {
            val pending = pendingBluetoothAction
            pendingBluetoothAction = null
            pending?.invoke()
            return
        }
        val stillMissing = PrinterPermissionHelper.missingPermissions(activity)
        if (stillMissing.isNotEmpty() && pendingBluetoothAction != null) {
            val labels = PrinterPermissionHelper.missingPermissionLabels(activity)
            Toast.makeText(
                activity,
                activity.getString(R.string.printer_permission_missing, labels.joinToString(", ")),
                Toast.LENGTH_LONG,
            ).show()
            PrinterPermissionHelper.request(activity)
            return
        }
        pendingBluetoothAction = null
        val missing = PrinterPermissionHelper.missingPermissionLabels(activity)
        val msg = if (missing.isNotEmpty()) {
            activity.getString(R.string.printer_permission_missing, missing.joinToString(", "))
        } else {
            activity.getString(R.string.printer_permission_denied)
        }
        Toast.makeText(activity, msg, Toast.LENGTH_LONG).show()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && shouldOfferSettings(activity)) {
            offerAppSettings(activity)
        }
    }

    private fun shouldOfferSettings(activity: Activity): Boolean {
        if (PrinterPermissionHelper.hasAll(activity)) return false
        val connectRationale = activity.shouldShowRequestPermissionRationale(
            Manifest.permission.BLUETOOTH_CONNECT,
        )
        val scanRationale = activity.shouldShowRequestPermissionRationale(
            Manifest.permission.BLUETOOTH_SCAN,
        )
        return !connectRationale && !scanRationale
    }

    private fun offerAppSettings(activity: Activity) {
        AlertDialog.Builder(activity)
            .setTitle(R.string.printer_permission_title)
            .setMessage(R.string.printer_permission_settings_hint)
            .setPositiveButton(R.string.printer_open_settings) { _, _ ->
                val intent = Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.fromParts("package", activity.packageName, null),
                )
                activity.startActivity(intent)
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    fun show(activity: AppCompatActivity, scope: CoroutineScope, storeName: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !hasBluetoothPermissions(activity)) {
            pendingBluetoothAction = { showInternal(activity, scope, storeName) }
            PrinterPermissionHelper.request(activity)
            Toast.makeText(activity, R.string.printer_permission_needed, Toast.LENGTH_LONG).show()
            return
        }
        try {
            showInternal(activity, scope, storeName)
        } catch (e: Exception) {
            android.util.Log.e("PrinterSetup", "Printer setup failed", e)
            Toast.makeText(
                activity,
                activity.getString(R.string.printer_failed, e.message ?: "error"),
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    private fun showInternal(activity: AppCompatActivity, scope: CoroutineScope, storeName: String) {
        val options = arrayOf(
            activity.getString(R.string.printer_transport_bluetooth),
            activity.getString(R.string.printer_transport_usb),
            activity.getString(R.string.printer_paper_width),
            activity.getString(R.string.printer_test),
            activity.getString(R.string.printer_clear),
        )
        AlertDialog.Builder(activity)
            .setTitle(R.string.printer_setup_title)
            .setSingleChoiceItems(options, -1) { dialog, which ->
                dialog.dismiss()
                when (which) {
                    0 -> showBluetoothPicker(activity, scope, storeName)
                    1 -> showUsbPicker(activity, scope, storeName)
                    2 -> showPaperWidth(activity)
                    3 -> runTest(activity, scope, storeName)
                    4 -> {
                        PrinterPreferences.clearPrinter(activity)
                        Toast.makeText(activity, R.string.printer_cleared, Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun showPaperWidth(activity: Activity) {
        val labels = activity.resources.getStringArray(R.array.printer_paper_widths)
        val values = intArrayOf(32, 48)
        val current = PrinterPreferences.getPaperWidth(activity)
        val index = values.indexOf(current).coerceAtLeast(0)
        AlertDialog.Builder(activity)
            .setTitle(R.string.printer_paper_width)
            .setSingleChoiceItems(labels, index) { dialog, which ->
                PrinterPreferences.setPaperWidth(activity, values[which])
                dialog.dismiss()
            }
            .show()
    }

    private fun showBluetoothPicker(
        activity: AppCompatActivity,
        scope: CoroutineScope,
        storeName: String,
    ) {
        withBluetoothPermission(activity) {
            openBluetoothPicker(activity)
        }
    }

    private fun openBluetoothPicker(activity: AppCompatActivity) {
        val adapter = BluetoothAdapter.getDefaultAdapter()
        if (adapter == null || !adapter.isEnabled) {
            Toast.makeText(activity, R.string.printer_bluetooth_off, Toast.LENGTH_LONG).show()
            return
        }
        @Suppress("MissingPermission")
        val bonded = adapter.bondedDevices?.sortedBy { it.name ?: it.address } ?: emptyList()
        if (bonded.isEmpty()) {
            AlertDialog.Builder(activity)
                .setTitle(R.string.printer_setup_title)
                .setMessage(R.string.printer_no_paired)
                .setPositiveButton(android.R.string.ok, null)
                .show()
            return
        }
        val labels = bonded.map { btLabel(it) }.toTypedArray()
        AlertDialog.Builder(activity)
            .setTitle(R.string.printer_transport_bluetooth)
            .setItems(labels) { _, which ->
                val device = bonded[which]
                @Suppress("MissingPermission")
                PrinterPreferences.saveBluetoothPrinter(
                    activity,
                    device.address,
                    device.name ?: device.address,
                )
                Toast.makeText(
                    activity,
                    activity.getString(R.string.printer_selected, btLabel(device)),
                    Toast.LENGTH_SHORT,
                ).show()
            }
            .show()
    }

    private fun showUsbPicker(
        activity: AppCompatActivity,
        scope: CoroutineScope,
        @Suppress("UNUSED_PARAMETER") storeName: String,
    ) {
        val devices = UsbEscPosPrinter.listPrinters(activity)
        if (devices.isEmpty()) {
            AlertDialog.Builder(activity)
                .setTitle(R.string.printer_transport_usb)
                .setMessage(R.string.printer_no_usb)
                .setPositiveButton(android.R.string.ok, null)
                .show()
            return
        }
        val labels = devices.map { usbLabel(it) }.toTypedArray()
        AlertDialog.Builder(activity)
            .setTitle(R.string.printer_transport_usb)
            .setItems(labels) { _, which ->
                val device = devices[which]
                scope.launch {
                    val granted = UsbEscPosPrinter.requestPermission(activity, device)
                    withContext(Dispatchers.Main) {
                        if (!granted) {
                            Toast.makeText(activity, R.string.printer_usb_denied, Toast.LENGTH_LONG).show()
                            return@withContext
                        }
                        PrinterPreferences.saveUsbPrinter(activity, device)
                        Toast.makeText(
                            activity,
                            activity.getString(R.string.printer_selected, usbLabel(device)),
                            Toast.LENGTH_SHORT,
                        ).show()
                    }
                }
            }
            .show()
    }

    private fun runTest(activity: AppCompatActivity, scope: CoroutineScope, storeName: String) {
        if (!PrinterPreferences.isConfigured(activity)) {
            Toast.makeText(activity, R.string.printer_none_selected, Toast.LENGTH_SHORT).show()
            return
        }
        val executeTest = { executeTestPrint(activity, scope, storeName) }
        if (PrinterPreferences.getTransport(activity) == PrinterTransport.BLUETOOTH) {
            withBluetoothPermission(activity, executeTest)
        } else {
            executeTest()
        }
    }

    private fun executeTestPrint(
        activity: AppCompatActivity,
        scope: CoroutineScope,
        storeName: String,
    ) {
        scope.launch {
            try {
                val result = NativeReceiptPrinter.printTest(activity, storeName)
                withContext(Dispatchers.Main) {
                    if (activity.isFinishing || activity.isDestroyed) return@withContext
                    if (result.isSuccess) {
                        Toast.makeText(activity, R.string.printer_test_ok, Toast.LENGTH_SHORT).show()
                    } else {
                        val err = result.exceptionOrNull()
                        val msg = when (err) {
                            is SecurityException -> activity.getString(R.string.printer_permission_needed)
                            else -> err?.message ?: "error"
                        }
                        Toast.makeText(
                            activity,
                            activity.getString(R.string.printer_failed, msg),
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("PrinterSetup", "Test print failed", e)
                withContext(Dispatchers.Main) {
                    if (!activity.isFinishing && !activity.isDestroyed) {
                        Toast.makeText(
                            activity,
                            activity.getString(R.string.printer_failed, e.message ?: "error"),
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }
            }
        }
    }

    @Suppress("MissingPermission")
    private fun btLabel(device: BluetoothDevice): String {
        val name = device.name
        return if (name.isNullOrBlank()) device.address else "$name (${device.address})"
    }

    private fun usbLabel(device: UsbDevice): String {
        val name = device.deviceName ?: "USB"
        return "$name [${device.vendorId}:${device.productId}]"
    }
}

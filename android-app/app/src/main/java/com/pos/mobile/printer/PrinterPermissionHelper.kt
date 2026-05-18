package com.pos.mobile.printer

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/** Runtime Bluetooth permissions for thermal printer (Android 12+). */
object PrinterPermissionHelper {

    const val REQUEST_CODE = 9101

    fun requiredPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.BLUETOOTH_SCAN,
            )
        } else {
            arrayOf(Manifest.permission.BLUETOOTH)
        }

    fun hasAll(context: Context): Boolean =
        requiredPermissions().all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        }

    fun missingPermissions(context: Context): Array<String> =
        requiredPermissions().filter {
            ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED
        }.toTypedArray()

    fun request(activity: Activity) {
        val missing = missingPermissions(activity)
        if (missing.isEmpty()) return
        val delegate = (activity as? androidx.appcompat.app.AppCompatActivity)
            ?.bluetoothPermissionDelegate
        if (delegate != null) {
            delegate.request()
        } else {
            ActivityCompat.requestPermissions(activity, missing, REQUEST_CODE)
        }
    }

    fun legacyResultsGranted(
        permissions: Array<out String>,
        grantResults: IntArray,
    ): Boolean {
        if (permissions.isEmpty() || grantResults.isEmpty()) return false
        return permissions.indices.all { i ->
            grantResults.getOrNull(i) == PackageManager.PERMISSION_GRANTED
        }
    }

    fun evaluateResults(context: Context, results: Map<String, Boolean>): Boolean =
        requiredPermissions().all { perm ->
            results[perm] == true ||
                ContextCompat.checkSelfPermission(context, perm) == PackageManager.PERMISSION_GRANTED
        }

    fun missingPermissionLabels(context: Context): List<String> =
        missingPermissions(context).map { permissionLabel(it) }

    private fun permissionLabel(permission: String): String = when (permission) {
        Manifest.permission.BLUETOOTH_CONNECT -> "Nearby devices (connect)"
        Manifest.permission.BLUETOOTH_SCAN -> "Nearby devices (scan)"
        Manifest.permission.BLUETOOTH -> "Bluetooth"
        else -> permission
    }

    /** @deprecated use [hasAll] */
    fun hasBluetoothConnect(context: Context): Boolean = hasAll(context)

    /** @deprecated use [missingPermissionLabels] */
    fun missingPermissionNames(context: Context): List<String> = missingPermissionLabels(context)
}

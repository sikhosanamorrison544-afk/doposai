package com.pos.mobile.printer

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import android.content.Intent as AndroidIntent
import kotlin.coroutines.resume

/** Raw ESC/POS over USB OTG (bulk OUT). Works with common thermal receipt printers. */
object UsbEscPosPrinter {

    private const val TAG = "UsbEscPos"
    const val ACTION_USB_PERMISSION = "com.pos.mobile.USB_PRINTER_PERMISSION"

    fun listPrinters(context: Context): List<UsbDevice> {
        val manager = context.getSystemService(Context.USB_SERVICE) as? UsbManager ?: return emptyList()
        return manager.deviceList.values
            .filter { findBulkOutEndpoint(it) != null }
            .sortedBy { it.deviceName ?: "" }
    }

    fun hasPermission(context: Context, device: UsbDevice): Boolean {
        val manager = context.getSystemService(Context.USB_SERVICE) as? UsbManager ?: return false
        return manager.hasPermission(device)
    }

    suspend fun requestPermission(context: Context, device: UsbDevice): Boolean {
        val manager = context.getSystemService(Context.USB_SERVICE) as? UsbManager ?: return false
        if (manager.hasPermission(device)) return true
        return withContext(Dispatchers.Main) {
            suspendCancellableCoroutine { cont ->
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(ctx: Context, intent: Intent) {
                    if (intent.action != ACTION_USB_PERMISSION) return
                    context.applicationContext.unregisterReceiver(this)
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    if (cont.isActive) cont.resume(granted)
                }
            }
            val filter = IntentFilter(ACTION_USB_PERMISSION)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.applicationContext.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                context.applicationContext.registerReceiver(receiver, filter)
            }
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
            val permissionIntent = AndroidIntent(ACTION_USB_PERMISSION).setPackage(context.packageName)
            val pi = PendingIntent.getBroadcast(
                context,
                device.deviceId,
                permissionIntent,
                flags,
            )
            manager.requestPermission(device, pi)
            }
        }
    }

    suspend fun print(context: Context, data: ByteArray): Result<Unit> = withContext(Dispatchers.IO) {
        val device = PrinterPreferences.findUsbDevice(context)
            ?: return@withContext Result.failure(IllegalStateException("No USB printer configured"))
        if (!hasPermission(context, device)) {
            val ok = requestPermission(context, device)
            if (!ok) return@withContext Result.failure(SecurityException("USB permission denied"))
        }
        val manager = context.getSystemService(Context.USB_SERVICE) as? UsbManager
            ?: return@withContext Result.failure(IllegalStateException("USB not available"))
        val endpointPair = findBulkOutEndpoint(device)
            ?: return@withContext Result.failure(IllegalStateException("No USB bulk OUT endpoint"))
        val (iface, endpoint) = endpointPair
        var connection: UsbDeviceConnection? = null
        try {
            connection = manager.openDevice(device)
                ?: return@withContext Result.failure(java.io.IOException("Could not open USB device"))
            if (!connection.claimInterface(iface, true)) {
                return@withContext Result.failure(java.io.IOException("Could not claim USB interface"))
            }
            var offset = 0
            val chunk = 4096
            while (offset < data.size) {
                val end = minOf(offset + chunk, data.size)
                val sent = connection.bulkTransfer(
                    endpoint,
                    data,
                    offset,
                    end - offset,
                    15_000,
                )
                if (sent < 0) {
                    return@withContext Result.failure(java.io.IOException("USB bulk transfer failed"))
                }
                offset += sent
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "USB print failed", e)
            Result.failure(e)
        } finally {
            try {
                connection?.releaseInterface(iface)
                connection?.close()
            } catch (_: Exception) {
            }
        }
    }

    private fun findBulkOutEndpoint(device: UsbDevice): Pair<UsbInterface, UsbEndpoint>? {
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            var out: UsbEndpoint? = null
            for (j in 0 until iface.endpointCount) {
                val ep = iface.getEndpoint(j)
                if (ep.direction == UsbConstants.USB_DIR_OUT &&
                    ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK
                ) {
                    out = ep
                    break
                }
            }
            if (out != null) return iface to out
        }
        return null
    }

}

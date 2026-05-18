package com.pos.mobile.printer

import android.content.Context
import android.content.SharedPreferences
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager

object PrinterPreferences {
    const val KEY_PRINTER_MAC = "bluetooth_printer_mac"
    const val KEY_PRINTER_NAME = "bluetooth_printer_name"
    const val KEY_TRANSPORT = "printer_transport"
    const val KEY_PAPER_WIDTH = "receipt_paper_width"
    const val KEY_USB_DEVICE_ID = "usb_printer_device_id"
    const val KEY_USB_VENDOR_ID = "usb_printer_vendor_id"
    const val KEY_USB_PRODUCT_ID = "usb_printer_product_id"
    const val KEY_USB_DEVICE_NAME = "usb_printer_device_name"
    const val DEFAULT_PAPER_WIDTH = 32

    fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences("pos", Context.MODE_PRIVATE)

    fun getTransport(context: Context): PrinterTransport {
        val p = prefs(context)
        return when (p.getString(KEY_TRANSPORT, "")?.lowercase()) {
            "usb" -> {
                if (p.getInt(KEY_USB_VENDOR_ID, -1) >= 0 && p.getInt(KEY_USB_PRODUCT_ID, -1) >= 0) {
                    PrinterTransport.USB
                } else {
                    PrinterTransport.NONE
                }
            }
            "bluetooth" -> {
                if (!p.getString(KEY_PRINTER_MAC, null).isNullOrBlank()) {
                    PrinterTransport.BLUETOOTH
                } else {
                    PrinterTransport.NONE
                }
            }
            else -> {
                if (!p.getString(KEY_PRINTER_MAC, null).isNullOrBlank()) {
                    PrinterTransport.BLUETOOTH
                } else {
                    PrinterTransport.NONE
                }
            }
        }
    }

    fun isConfigured(context: Context): Boolean =
        getTransport(context) != PrinterTransport.NONE

    fun getPrinterMac(context: Context): String? =
        prefs(context).getString(KEY_PRINTER_MAC, null)?.takeIf { it.isNotBlank() }

    fun getPrinterName(context: Context): String? =
        prefs(context).getString(KEY_PRINTER_NAME, null)

    fun getPaperWidth(context: Context): Int =
        prefs(context).getInt(KEY_PAPER_WIDTH, DEFAULT_PAPER_WIDTH).coerceIn(32, 48)

    fun saveBluetoothPrinter(context: Context, mac: String, name: String) {
        prefs(context).edit()
            .putString(KEY_TRANSPORT, "bluetooth")
            .putString(KEY_PRINTER_MAC, mac)
            .putString(KEY_PRINTER_NAME, name)
            .apply()
    }

    fun saveUsbPrinter(context: Context, device: UsbDevice) {
        prefs(context).edit()
            .putString(KEY_TRANSPORT, "usb")
            .putInt(KEY_USB_DEVICE_ID, device.deviceId)
            .putInt(KEY_USB_VENDOR_ID, device.vendorId)
            .putInt(KEY_USB_PRODUCT_ID, device.productId)
            .putString(KEY_USB_DEVICE_NAME, device.deviceName ?: "USB printer")
            .remove(KEY_PRINTER_MAC)
            .apply()
    }

    fun clearPrinter(context: Context) {
        prefs(context).edit()
            .remove(KEY_TRANSPORT)
            .remove(KEY_PRINTER_MAC)
            .remove(KEY_PRINTER_NAME)
            .remove(KEY_USB_DEVICE_ID)
            .remove(KEY_USB_VENDOR_ID)
            .remove(KEY_USB_PRODUCT_ID)
            .remove(KEY_USB_DEVICE_NAME)
            .apply()
    }

    fun setPaperWidth(context: Context, width: Int) {
        prefs(context).edit()
            .putInt(KEY_PAPER_WIDTH, width.coerceIn(32, 48))
            .apply()
    }

    fun getUsbLabel(context: Context): String? =
        prefs(context).getString(KEY_USB_DEVICE_NAME, null)

    fun findUsbDevice(context: Context): UsbDevice? {
        val p = prefs(context)
        val deviceId = p.getInt(KEY_USB_DEVICE_ID, -1)
        val vendorId = p.getInt(KEY_USB_VENDOR_ID, -1)
        val productId = p.getInt(KEY_USB_PRODUCT_ID, -1)
        if (vendorId < 0 || productId < 0) return null
        val manager = context.getSystemService(Context.USB_SERVICE) as? UsbManager ?: return null
        val devices = manager.deviceList.values
        devices.firstOrNull { it.deviceId == deviceId }?.let { return it }
        return devices.firstOrNull { it.vendorId == vendorId && it.productId == productId }
    }

    /** @deprecated use [saveBluetoothPrinter] */
    fun savePrinter(context: Context, mac: String, name: String) = saveBluetoothPrinter(context, mac, name)
}

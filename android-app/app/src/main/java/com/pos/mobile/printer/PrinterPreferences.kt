package com.pos.mobile.printer

import android.content.Context
import android.content.SharedPreferences
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager

object PrinterPreferences {
    const val KEY_PRINTER_MAC = "bluetooth_printer_mac"
    const val KEY_PRINTER_NAME = "bluetooth_printer_name"
    const val KEY_TRANSPORT = "printer_transport"
    const val KEY_PREFERRED_TRANSPORT = "printer_preferred_transport"
    const val KEY_PAPER_WIDTH = "receipt_paper_width"
    const val KEY_USB_DEVICE_ID = "usb_printer_device_id"
    const val KEY_USB_VENDOR_ID = "usb_printer_vendor_id"
    const val KEY_USB_PRODUCT_ID = "usb_printer_product_id"
    const val KEY_USB_DEVICE_NAME = "usb_printer_device_name"
    /** Character width for 58mm thermal paper (default). Use 48 for 80mm. */
    const val CHAR_WIDTH_58MM = 32
    const val CHAR_WIDTH_80MM = 48
    const val DEFAULT_PAPER_WIDTH = CHAR_WIDTH_58MM

    fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences("pos", Context.MODE_PRIVATE)

    fun hasBluetoothPrinter(context: Context): Boolean =
        !getPrinterMac(context).isNullOrBlank()

    fun hasUsbPrinter(context: Context): Boolean =
        findUsbDevice(context) != null

    fun getTransport(context: Context): PrinterTransport =
        resolvePrintTransport(context, null)

    fun resolvePrintTransport(context: Context, override: String?): PrinterTransport {
        val hasBt = hasBluetoothPrinter(context)
        val hasUsb = hasUsbPrinter(context)
        when (override?.lowercase()?.trim()) {
            "usb" -> if (hasUsb) return PrinterTransport.USB
            "bluetooth" -> if (hasBt) return PrinterTransport.BLUETOOTH
        }
        val pref = prefs(context).getString(KEY_PREFERRED_TRANSPORT, null)
            ?: prefs(context).getString(KEY_TRANSPORT, "auto")
        when (pref?.lowercase()) {
            "usb" -> if (hasUsb) return PrinterTransport.USB
            "bluetooth" -> if (hasBt) return PrinterTransport.BLUETOOTH
        }
        return when {
            hasUsb && !hasBt -> PrinterTransport.USB
            hasBt && !hasUsb -> PrinterTransport.BLUETOOTH
            hasUsb && hasBt -> when (prefs(context).getString(KEY_TRANSPORT, "usb")?.lowercase()) {
                "bluetooth" -> PrinterTransport.BLUETOOTH
                else -> PrinterTransport.USB
            }
            else -> PrinterTransport.NONE
        }
    }

    fun isConfigured(context: Context): Boolean =
        hasBluetoothPrinter(context) || hasUsbPrinter(context)

    fun getPrinterMac(context: Context): String? =
        prefs(context).getString(KEY_PRINTER_MAC, null)?.takeIf { it.isNotBlank() }

    fun getPrinterName(context: Context): String? =
        prefs(context).getString(KEY_PRINTER_NAME, null)

    fun getPaperWidth(context: Context): Int =
        prefs(context).getInt(KEY_PAPER_WIDTH, DEFAULT_PAPER_WIDTH).coerceIn(32, 48)

    fun saveBluetoothPrinter(context: Context, mac: String, name: String) {
        val p = prefs(context)
        val editor = p.edit()
            .putString(KEY_TRANSPORT, "bluetooth")
            .putString(KEY_PREFERRED_TRANSPORT, "bluetooth")
            .putString(KEY_PRINTER_MAC, mac)
            .putString(KEY_PRINTER_NAME, name)
        if (!p.contains(KEY_PAPER_WIDTH)) {
            editor.putInt(KEY_PAPER_WIDTH, DEFAULT_PAPER_WIDTH)
        }
        editor.apply()
    }

    fun saveUsbPrinter(context: Context, device: UsbDevice) {
        val p = prefs(context)
        val editor = p.edit()
            .putString(KEY_TRANSPORT, "usb")
            .putString(KEY_PREFERRED_TRANSPORT, "usb")
            .putInt(KEY_USB_DEVICE_ID, device.deviceId)
            .putInt(KEY_USB_VENDOR_ID, device.vendorId)
            .putInt(KEY_USB_PRODUCT_ID, device.productId)
            .putString(KEY_USB_DEVICE_NAME, device.deviceName ?: "USB printer")
        if (!p.contains(KEY_PAPER_WIDTH)) {
            editor.putInt(KEY_PAPER_WIDTH, DEFAULT_PAPER_WIDTH)
        }
        editor.apply()
    }

    fun setPreferredTransport(context: Context, transport: String) {
        prefs(context).edit()
            .putString(KEY_PREFERRED_TRANSPORT, transport.lowercase())
            .apply()
    }

    fun clearPrinter(context: Context) {
        prefs(context).edit()
            .remove(KEY_TRANSPORT)
            .remove(KEY_PREFERRED_TRANSPORT)
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

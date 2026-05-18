package com.pos.mobile.printer

import android.content.Context

/** Routes ESC/POS bytes to the configured Bluetooth or USB thermal printer. */
object ThermalPrintService {

    suspend fun print(context: Context, data: ByteArray): Result<Unit> {
        return when (PrinterPreferences.getTransport(context)) {
            PrinterTransport.BLUETOOTH -> {
                val mac = PrinterPreferences.getPrinterMac(context)
                    ?: return Result.failure(IllegalStateException("No Bluetooth printer configured"))
                BluetoothEscPosPrinter.print(context, mac, data)
            }
            PrinterTransport.USB -> UsbEscPosPrinter.print(context, data)
            PrinterTransport.NONE -> Result.failure(IllegalStateException("No printer configured"))
        }
    }
}

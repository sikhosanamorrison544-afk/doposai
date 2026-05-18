package com.pos.mobile.printer

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.IOException
import java.util.UUID

/** Sends raw ESC/POS bytes to a paired Bluetooth thermal printer (SPP). */
object BluetoothEscPosPrinter {

    private const val TAG = "BluetoothEscPos"
    private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

    suspend fun print(context: Context, macAddress: String, data: ByteArray): Result<Unit> =
        withContext(Dispatchers.IO) {
            if (!PrinterPermissionHelper.hasAll(context)) {
                val missing = PrinterPermissionHelper.missingPermissionNames(context).joinToString(", ")
                return@withContext Result.failure(
                    SecurityException("Allow Bluetooth permissions: $missing"),
                )
            }
            try {
                val adapter = BluetoothAdapter.getDefaultAdapter()
                    ?: return@withContext Result.failure(IllegalStateException("Bluetooth not available"))
                if (!adapter.isEnabled) {
                    return@withContext Result.failure(IllegalStateException("Turn on Bluetooth"))
                }
                @Suppress("MissingPermission")
                val device: BluetoothDevice = try {
                    adapter.getRemoteDevice(macAddress)
                } catch (e: IllegalArgumentException) {
                    return@withContext Result.failure(IllegalArgumentException("Invalid printer address"))
                }
                adapter.cancelDiscovery()
                var socket: BluetoothSocket? = null
                try {
                    withTimeout(CONNECT_TIMEOUT_MS) {
                        socket = connectSocket(device)
                        val out = socket!!.outputStream
                        var offset = 0
                        val chunk = 1024
                        while (offset < data.size) {
                            val end = minOf(offset + chunk, data.size)
                            out.write(data, offset, end - offset)
                            offset = end
                        }
                        out.flush()
                    }
                    Result.success(Unit)
                } finally {
                    try {
                        socket?.close()
                    } catch (_: IOException) {
                    }
                }
            } catch (e: SecurityException) {
                Log.e(TAG, "Bluetooth permission denied", e)
                Result.failure(e)
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                Log.e(TAG, "Bluetooth print timed out", e)
                Result.failure(IOException("Printer connection timed out"))
            } catch (e: IOException) {
                Log.e(TAG, "Bluetooth print failed", e)
                Result.failure(e)
            } catch (e: Exception) {
                Log.e(TAG, "Bluetooth print error", e)
                Result.failure(e)
            }
        }

    @Suppress("MissingPermission")
    private fun connectSocket(device: BluetoothDevice): BluetoothSocket {
        val spp = device.createRfcommSocketToServiceRecord(SPP_UUID)
        return try {
            spp.connect()
            spp
        } catch (first: IOException) {
            try {
                spp.close()
            } catch (_: IOException) {
            }
            val fallback = reflectRfcommSocket(device)
            fallback.connect()
            fallback
        }
    }

    @Suppress("MissingPermission")
    private fun reflectRfcommSocket(device: BluetoothDevice): BluetoothSocket {
        return try {
            val method = device.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
            @Suppress("UNCHECKED_CAST")
            method.invoke(device, 1) as BluetoothSocket
        } catch (e: Exception) {
            throw IOException("Could not open Bluetooth printer connection", e)
        }
    }

    private const val CONNECT_TIMEOUT_MS = 20_000L
}

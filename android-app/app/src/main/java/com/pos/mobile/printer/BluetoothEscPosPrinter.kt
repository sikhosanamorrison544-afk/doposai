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
    private const val CONNECT_TIMEOUT_MS = 8_000L

    @Volatile
    private var warmSocket: BluetoothSocket? = null

    @Volatile
    private var warmMac: String? = null

    private val socketLock = Any()

    /** Open Bluetooth SPP ahead of checkout so the first receipt prints faster. */
    suspend fun preconnect(context: Context, macAddress: String): Result<Unit> =
        withContext(Dispatchers.IO) {
            if (!PrinterPermissionHelper.hasAll(context)) {
                return@withContext Result.failure(
                    SecurityException("Bluetooth permissions not granted"),
                )
            }
            synchronized(socketLock) {
                if (warmMac == macAddress && isSocketAlive(warmSocket)) {
                    return@withContext Result.success(Unit)
                }
                releaseLocked()
            }
            try {
                withTimeout(CONNECT_TIMEOUT_MS) {
                    val socket = openSocket(context, macAddress)
                    synchronized(socketLock) {
                        warmSocket = socket
                        warmMac = macAddress
                    }
                }
                Result.success(Unit)
            } catch (e: Exception) {
                Log.w(TAG, "Preconnect failed", e)
                Result.failure(e)
            }
        }

    fun releaseWarmConnection() {
        synchronized(socketLock) {
            releaseLocked()
        }
    }

    suspend fun print(context: Context, macAddress: String, data: ByteArray): Result<Unit> =
        withContext(Dispatchers.IO) {
            if (!PrinterPermissionHelper.hasAll(context)) {
                val missing = PrinterPermissionHelper.missingPermissionNames(context).joinToString(", ")
                return@withContext Result.failure(
                    SecurityException("Allow Bluetooth permissions: $missing"),
                )
            }
            try {
                var socket: BluetoothSocket? = null
                var ownedSocket = false
                synchronized(socketLock) {
                    if (warmMac == macAddress && isSocketAlive(warmSocket)) {
                        socket = warmSocket
                    }
                }
                if (socket == null) {
                    withTimeout(CONNECT_TIMEOUT_MS) {
                        socket = openSocket(context, macAddress)
                        ownedSocket = true
                    }
                }
                try {
                    withTimeout(WRITE_TIMEOUT_MS) {
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
                    synchronized(socketLock) {
                        if (ownedSocket) {
                            warmSocket = socket
                            warmMac = macAddress
                        }
                    }
                    Result.success(Unit)
                } catch (e: Exception) {
                    synchronized(socketLock) {
                        if (warmSocket === socket) {
                            releaseLocked()
                        }
                    }
                    if (ownedSocket) {
                        try {
                            socket?.close()
                        } catch (_: IOException) {
                        }
                    }
                    throw e
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
    private fun openSocket(context: Context, macAddress: String): BluetoothSocket {
        val adapter = BluetoothAdapter.getDefaultAdapter()
            ?: throw IllegalStateException("Bluetooth not available")
        if (!adapter.isEnabled) {
            throw IllegalStateException("Turn on Bluetooth")
        }
        val device = try {
            adapter.getRemoteDevice(macAddress)
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("Invalid printer address")
        }
        adapter.cancelDiscovery()
        return connectSocket(device)
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

    private fun isSocketAlive(socket: BluetoothSocket?): Boolean {
        return try {
            socket?.isConnected == true
        } catch (_: Exception) {
            false
        }
    }

    private fun releaseLocked() {
        try {
            warmSocket?.close()
        } catch (_: IOException) {
        }
        warmSocket = null
        warmMac = null
    }

    private const val WRITE_TIMEOUT_MS = 5_000L
}

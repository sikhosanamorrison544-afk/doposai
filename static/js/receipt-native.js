/**
 * Thermal printing: Android bridge (BT/USB), WebUSB, and Web Serial (Bluetooth SPP on desktop).
 */
(function (global) {
    'use strict';

    const USB_FILTERS = [{ classCode: 7 }, { classCode: 255 }];
    const SERIAL_BAUD = 9600;

    function canUsb() {
        return !!(global.navigator && global.navigator.usb);
    }

    function canSerial() {
        return !!(global.navigator && global.navigator.serial);
    }

    function isAndroidNative() {
        try {
            if (!global.posNativePrint || typeof global.posNativePrint.isAvailable !== 'function') {
                return false;
            }
            const info = global.posNativePrint.isAvailable();
            return !!(info && info.native);
        } catch (e) {
            return false;
        }
    }

    function findBulkOut(device) {
        for (let i = 0; i < device.configuration.interfaces.length; i++) {
            const iface = device.configuration.interfaces[i];
            for (let j = 0; j < iface.alternates.length; j++) {
                const alt = iface.alternates[j];
                for (let k = 0; k < alt.endpoints.length; k++) {
                    const ep = alt.endpoints[k];
                    if (ep.direction === 'out' && ep.type === 'bulk') {
                        return { iface: iface, alternate: alt, endpoint: ep };
                    }
                }
            }
        }
        return null;
    }

    async function getUsbDevice() {
        const list = await navigator.usb.getDevices();
        if (list.length) return list[0];
        return navigator.usb.requestDevice({ filters: USB_FILTERS });
    }

    async function sendEscPosUsb(bytes) {
        const device = await getUsbDevice();
        await device.open();
        if (!device.configuration) {
            await device.selectConfiguration(1);
        }
        const match = findBulkOut(device);
        if (!match) throw new Error('No USB bulk OUT endpoint');
        await device.claimInterface(match.iface.interfaceNumber);
        const chunk = 4096;
        for (let off = 0; off < bytes.length; off += chunk) {
            const slice = bytes.subarray(off, Math.min(off + chunk, bytes.length));
            await device.transferOut(match.endpoint.endpointNumber, slice);
        }
        try {
            await device.releaseInterface(match.iface.interfaceNumber);
        } catch (e) {
            /* ignore */
        }
        try {
            await device.close();
        } catch (e) {
            /* ignore */
        }
    }

    async function getSerialPort() {
        const ports = await navigator.serial.getPorts();
        if (ports.length) return ports[0];
        return navigator.serial.requestPort();
    }

    async function sendEscPosSerial(bytes) {
        const port = await getSerialPort();
        await port.open({ baudRate: SERIAL_BAUD });
        const writer = port.writable.getWriter();
        const chunk = 1024;
        try {
            for (let off = 0; off < bytes.length; off += chunk) {
                const slice = bytes.subarray(off, Math.min(off + chunk, bytes.length));
                await writer.write(slice);
            }
        } finally {
            writer.releaseLock();
        }
        await port.close();
    }

    async function probeWebAvailability() {
        const out = { usb: false, bluetooth: false };
        if (canUsb()) {
            try {
                const devices = await navigator.usb.getDevices();
                out.usb = devices.length > 0;
            } catch (e) {
                out.usb = false;
            }
        }
        if (canSerial()) {
            try {
                const ports = await navigator.serial.getPorts();
                out.bluetooth = ports.length > 0;
            } catch (e) {
                out.bluetooth = false;
            }
        }
        return out;
    }

    function getNativeAvailability() {
        try {
            if (!global.posNativePrint || typeof global.posNativePrint.isAvailable !== 'function') {
                return { native: false, usb: false, bluetooth: false, configured: false };
            }
            const info = global.posNativePrint.isAvailable();
            return {
                native: true,
                usb: !!info.usb,
                bluetooth: !!info.bluetooth,
                configured: !!info.configured,
                transport: info.transport || '',
                paperWidth: info.paperWidth,
            };
        } catch (e) {
            return { native: false, usb: false, bluetooth: false, configured: false };
        }
    }

    function showTransportChooser() {
        return new Promise(function (resolve) {
            const backdrop = document.createElement('div');
            backdrop.className = 'panel-backdrop';
            backdrop.style.cssText =
                'display:block!important;position:fixed;inset:0;z-index:10050;background:rgba(0,0,0,0.45);';

            const box = document.createElement('div');
            box.className = 'card';
            box.style.cssText =
                'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:10051;max-width:360px;width:90vw;padding:20px;';

            box.innerHTML =
                '<h3 style="margin:0 0 12px 0;">Choose printer</h3>' +
                '<p style="margin:0 0 16px 0;opacity:0.85;">Both USB and Bluetooth printers are available.</p>' +
                '<div style="display:flex;flex-direction:column;gap:8px;">' +
                '<button type="button" class="primary" data-transport="usb">USB printer</button>' +
                '<button type="button" class="primary" data-transport="bluetooth">Bluetooth printer</button>' +
                '<button type="button" class="small" data-transport="cancel">Cancel</button>' +
                '</div>';

            function cleanup(value) {
                backdrop.remove();
                resolve(value);
            }

            box.querySelectorAll('button').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const t = btn.getAttribute('data-transport');
                    cleanup(t === 'cancel' ? null : t);
                });
            });

            backdrop.addEventListener('click', function (e) {
                if (e.target === backdrop) cleanup(null);
            });

            document.body.appendChild(backdrop);
            document.body.appendChild(box);
        });
    }

    async function resolveTransport() {
        if (isAndroidNative()) {
            const info = getNativeAvailability();
            if (!info.configured && !info.usb && !info.bluetooth) return null;
            const pref =
                global.posWebPrinterPrefs && global.posWebPrinterPrefs.getPreference
                    ? global.posWebPrinterPrefs.getPreference()
                    : 'auto';
            if (pref === 'usb' && info.usb) return 'usb';
            if (pref === 'bluetooth' && info.bluetooth) return 'bluetooth';
            if (info.usb && !info.bluetooth) return 'usb';
            if (info.bluetooth && !info.usb) return 'bluetooth';
            if (info.usb && info.bluetooth) {
                if (pref === 'auto') return showTransportChooser();
                return pref === 'usb' ? 'usb' : 'bluetooth';
            }
            if (info.configured && info.transport) return info.transport;
            return null;
        }

        const avail = await probeWebAvailability();
        const pref =
            global.posWebPrinterPrefs && global.posWebPrinterPrefs.getPreference
                ? global.posWebPrinterPrefs.getPreference()
                : 'auto';

        if (pref === 'usb' && avail.usb) return 'usb';
        if (pref === 'bluetooth' && avail.bluetooth) return 'bluetooth';
        if (avail.usb && !avail.bluetooth) return 'usb';
        if (avail.bluetooth && !avail.usb) return 'bluetooth';
        if (avail.usb && avail.bluetooth) {
            if (pref === 'auto') return showTransportChooser();
            return pref === 'usb' ? 'usb' : 'bluetooth';
        }
        return null;
    }

    function buildEscPosBytes(type, opts) {
        if (!global.posEscPos) return null;
        const width =
            global.posWebPrinterPrefs && global.posWebPrinterPrefs.getPaperWidth
                ? global.posWebPrinterPrefs.getPaperWidth()
                : global.posEscPos.getPaperWidth();
        return type === 'withdrawal'
            ? global.posEscPos.buildWithdrawal(opts, width)
            : global.posEscPos.buildSale(opts, width);
    }

    async function printThermal(type, opts, transport) {
        const bytes = buildEscPosBytes(type, opts);
        if (!bytes) throw new Error('ESC/POS builder not loaded');

        if (isAndroidNative()) {
            const fn = type === 'withdrawal' ? 'printWithdrawal' : 'printSale';
            if (typeof global.posNativePrint[fn] !== 'function') {
                throw new Error('Native print unavailable');
            }
            const r = global.posNativePrint[fn](opts, transport || '');
            if (!r || !r.ok) throw new Error((r && r.error) || 'Print failed');
            return true;
        }

        if (transport === 'usb') {
            await sendEscPosUsb(bytes);
            return true;
        }
        if (transport === 'bluetooth') {
            await sendEscPosSerial(bytes);
            return true;
        }
        throw new Error('No printer transport');
    }

    async function requestUsbPrinter() {
        if (!canUsb()) {
            alert('WebUSB is not available. Use Chrome or Edge on desktop.');
            return false;
        }
        await navigator.usb.requestDevice({ filters: USB_FILTERS });
        return true;
    }

    async function requestBluetoothPrinter() {
        if (!canSerial()) {
            alert(
                'Web Serial is not available. Pair your Bluetooth printer in system settings, then use Chrome or Edge on desktop.',
            );
            return false;
        }
        await navigator.serial.requestPort();
        return true;
    }

    /**
     * Thermal print with auto USB/BT selection. Returns true if handled.
     */
    async function routePrintAsync(type, opts, printWindow, onFallback) {
        try {
            const transport = await resolveTransport();
            if (!transport) return false;
            await printThermal(type, opts, transport);
            if (printWindow && !printWindow.closed) printWindow.close();
            return true;
        } catch (err) {
            console.warn('Thermal print failed:', err);
            if (typeof onFallback === 'function') onFallback(err);
            return false;
        }
    }

    /** @deprecated use routePrintAsync */
    function routePrint(type, opts, printWindow, onFallback) {
        routePrintAsync(type, opts, printWindow, onFallback).catch(function () {
            if (typeof onFallback === 'function') onFallback();
        });
        return isAndroidNative() || canUsb() || canSerial();
    }

    global.posWebPrint = {
        canUsb: canUsb,
        canSerial: canSerial,
        probeWebAvailability: probeWebAvailability,
        getNativeAvailability: getNativeAvailability,
        resolveTransport: resolveTransport,
        requestUsbPrinter: requestUsbPrinter,
        requestBluetoothPrinter: requestBluetoothPrinter,
        routePrint: routePrint,
        routePrintAsync: routePrintAsync,
        printSale: function (opts, transport) {
            return printThermal('sale', opts, transport);
        },
        printWithdrawal: function (opts, transport) {
            return printThermal('withdrawal', opts, transport);
        },
    };
})(typeof window !== 'undefined' ? window : global);

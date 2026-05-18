/**
 * Native thermal printing: Android WebView bridge (Bluetooth/USB) and WebUSB on laptop Chrome.
 */
(function (global) {
    'use strict';

    const USB_FILTERS = [{ classCode: 7 }, { classCode: 255 }];

    function canUsb() {
        return !!(global.navigator && global.navigator.usb);
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

    async function sendEscPos(bytes) {
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
        } catch (e) { /* ignore */ }
        try {
            await device.close();
        } catch (e) { /* ignore */ }
        return true;
    }

    function tryAndroid(type, opts) {
        if (!global.posNativePrint || typeof global.posNativePrint.isAvailable !== 'function') {
            return false;
        }
        const info = global.posNativePrint.isAvailable();
        if (!info || !info.configured) return false;
        const fn = type === 'withdrawal' ? 'printWithdrawal' : 'printSale';
        if (typeof global.posNativePrint[fn] !== 'function') return false;
        const r = global.posNativePrint[fn](opts);
        return !!(r && r.ok);
    }

    async function printUsb(type, opts) {
        if (!canUsb() || !global.posEscPos) return false;
        const width = global.posEscPos.getPaperWidth();
        const bytes =
            type === 'withdrawal'
                ? global.posEscPos.buildWithdrawal(opts, width)
                : global.posEscPos.buildSale(opts, width);
        await sendEscPos(bytes);
        return true;
    }

    async function requestUsbPrinter() {
        if (!canUsb()) {
            alert('WebUSB is not available. Use Chrome/Edge on desktop with a USB thermal printer.');
            return false;
        }
        await navigator.usb.requestDevice({ filters: USB_FILTERS });
        return true;
    }

    /**
     * Try thermal print (Android native or WebUSB). Returns true if handled (incl. async USB).
     * onFallback called when thermal print unavailable or fails.
     */
    function routePrint(type, opts, printWindow, onFallback) {
        if (tryAndroid(type, opts)) {
            if (printWindow && !printWindow.closed) printWindow.close();
            return true;
        }
        if (canUsb() && global.posEscPos) {
            printUsb(type, opts)
                .then(function () {
                    if (printWindow && !printWindow.closed) printWindow.close();
                })
                .catch(function (err) {
                    console.warn('WebUSB print failed:', err);
                    if (typeof onFallback === 'function') onFallback();
                });
            return true;
        }
        return false;
    }

    global.posWebPrint = {
        canUsb: canUsb,
        requestUsbPrinter: requestUsbPrinter,
        routePrint: routePrint,
        printSale: function (opts) {
            return printUsb('sale', opts);
        },
        printWithdrawal: function (opts) {
            return printUsb('withdrawal', opts);
        },
    };
})(typeof window !== 'undefined' ? window : global);

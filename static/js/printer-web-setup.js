/**
 * Store settings UI for web USB / Bluetooth thermal printers.
 */
(function () {
    'use strict';

    function isAndroidApp() {
        return (
            (typeof window.isPosAndroidWebView === 'function' && window.isPosAndroidWebView()) ||
            document.body.classList.contains('pos-android-app')
        );
    }

    async function refreshStatus() {
        const el = document.getElementById('web-printer-status');
        if (!el) return;

        let usb = false;
        let bt = false;
        let native = false;

        if (window.posWebPrint) {
            if (window.posWebPrint.getNativeAvailability) {
                const n = window.posWebPrint.getNativeAvailability();
                native = n.native;
                usb = usb || n.usb;
                bt = bt || n.bluetooth;
            }
            if (!native && window.posWebPrint.probeWebAvailability) {
                const w = await window.posWebPrint.probeWebAvailability();
                usb = usb || w.usb;
                bt = bt || w.bluetooth;
            }
        }

        const parts = [];
        if (native) parts.push('Android app');
        parts.push('USB: ' + (usb ? 'ready' : 'not connected'));
        parts.push('Bluetooth: ' + (bt ? 'ready' : 'not connected'));
        el.textContent = parts.join(' · ');

        const pref = document.getElementById('web-printer-preference');
        if (pref && window.posWebPrinterPrefs) {
            pref.value = window.posWebPrinterPrefs.getPreference();
        }
        const width = document.getElementById('web-printer-paper-width');
        if (width && window.posWebPrinterPrefs) {
            width.value = String(window.posWebPrinterPrefs.getPaperWidth());
        }
    }

    function initWebPrinterSetup() {
        const section = document.getElementById('web-printer-section');
        if (!section) return;
        if (isAndroidApp()) {
            section.style.display = 'none';
            return;
        }

        const msg = document.getElementById('web-printer-message');
        function setMsg(text, ok) {
            if (!msg) return;
            msg.textContent = text || '';
            msg.style.color = ok ? 'rgba(34, 197, 94, 1)' : 'rgba(239, 68, 68, 1)';
        }

        document.getElementById('btn-connect-usb-printer')?.addEventListener('click', async function () {
            try {
                if (!window.posWebPrint?.requestUsbPrinter) {
                    setMsg('WebUSB not supported in this browser.', false);
                    return;
                }
                await window.posWebPrint.requestUsbPrinter();
                setMsg('USB printer authorized. You can print receipts.', true);
                await refreshStatus();
            } catch (e) {
                setMsg(e.message || 'USB setup failed', false);
            }
        });

        document.getElementById('btn-connect-bt-printer')?.addEventListener('click', async function () {
            try {
                if (!window.posWebPrint?.requestBluetoothPrinter) {
                    setMsg('Web Serial not supported. Use Chrome/Edge and pair the printer in system settings.', false);
                    return;
                }
                await window.posWebPrint.requestBluetoothPrinter();
                setMsg('Bluetooth/serial port authorized.', true);
                await refreshStatus();
            } catch (e) {
                setMsg(e.message || 'Bluetooth setup failed', false);
            }
        });

        document.getElementById('web-printer-preference')?.addEventListener('change', function (e) {
            if (window.posWebPrinterPrefs) {
                window.posWebPrinterPrefs.setPreference(e.target.value);
            }
        });

        document.getElementById('web-printer-paper-width')?.addEventListener('change', function (e) {
            if (window.posWebPrinterPrefs) {
                window.posWebPrinterPrefs.setPaperWidth(parseInt(e.target.value, 10));
            }
        });

        document.getElementById('btn-test-web-printer')?.addEventListener('click', async function () {
            try {
                if (!window.posWebPrint || !window.posEscPos) {
                    setMsg('Printer modules not loaded.', false);
                    return;
                }
                const store = { store_name: document.querySelector('.shop-name')?.textContent?.trim() || 'POS' };
                const transport = await window.posWebPrint.resolveTransport();
                if (!transport) {
                    setMsg('Connect a USB or Bluetooth printer first.', false);
                    return;
                }
                await window.posWebPrint.printSale(
                    {
                        saleId: 'TEST',
                        createdAt: new Date().toISOString(),
                        cashierName: 'Test',
                        items: [{ name: 'Test item', qty: 1, unit_price: 1, line_total: 1 }],
                        subtotal: 1,
                        discountTotal: 0,
                        total: 1,
                        payments: [{ method: 'cash', amount: 1 }],
                        store: store,
                    },
                    transport,
                );
                setMsg('Test receipt sent to ' + transport + ' printer.', true);
            } catch (e) {
                setMsg(e.message || 'Test print failed', false);
            }
        });

        refreshStatus();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initWebPrinterSetup);
    } else {
        initWebPrinterSetup();
    }
})();

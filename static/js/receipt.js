/**
 * Browser receipt printing. Server ESC/POS only works with a local USB printer.
 * Call preparePrintWindow() before await (keeps user-gesture); finish with printSaleReceipt().
 */
(function (global) {
    'use strict';

    let storeSettings = null;

    function formatMoney(n) {
        return Number(n || 0).toFixed(2);
    }

    function methodLabel(method) {
        const map = {
            cash: 'Cash',
            mobile_money: 'Mobile Money',
            card: 'Card',
            credit: 'Credit',
        };
        return map[method] || String(method || '').replace(/_/g, ' ');
    }

    function escapeHtml(text) {
        if (text == null) return '';
        const el = document.createElement('div');
        el.textContent = String(text);
        return el.innerHTML;
    }

    function receiptStyles() {
        return [
            '@page { size: 80mm auto; margin: 4mm; }',
            'body { font-family: monospace, "Courier New", Courier, sans-serif; font-size: 12px;',
            'margin: 0; padding: 8px; color: #000; background: #fff; width: 72mm; max-width: 72mm; }',
            '.store { text-align: center; font-weight: bold; font-size: 14px; text-transform: uppercase; }',
            '.meta { margin: 8px 0; } .meta div { margin: 2px 0; }',
            'hr { border: none; border-top: 1px dashed #000; margin: 6px 0; }',
            'table { width: 100%; border-collapse: collapse; } td { vertical-align: top; padding: 2px 0; }',
            '.item-name { font-weight: bold; } .total-row { font-weight: bold; font-size: 13px; }',
            '.footer { text-align: center; margin-top: 10px; font-size: 11px; }',
            '@media print { body { width: 72mm; } }',
        ].join('\n');
    }

    function wrapReceiptHtml(title, bodyHtml) {
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' +
            escapeHtml(title) +
            '</title><style>' +
            receiptStyles() +
            '</style></head><body>' +
            bodyHtml +
            '</body></html>'
        );
    }

    /** Open during click handler, before any await (required for print dialog). */
    function preparePrintWindow() {
        try {
            const w = window.open('', 'pos_receipt_print', 'width=420,height=700,scrollbars=yes');
            if (w) {
                w.document.open();
                w.document.write('<html><body style="font-family:sans-serif;padding:16px">Preparing receipt…</body></html>');
                w.document.close();
            }
            return w;
        } catch (e) {
            console.warn('preparePrintWindow failed:', e);
            return null;
        }
    }

    function showReceiptModal(fullHtml, title) {
        const existing = document.getElementById('receipt-print-modal');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'receipt-print-modal';
        overlay.style.cssText =
            'position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;padding:12px;box-sizing:border-box';

        const panel = document.createElement('div');
        panel.style.cssText =
            'background:#fff;color:#000;max-width:420px;width:100%;max-height:90vh;display:flex;flex-direction:column;border-radius:8px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,.3)';

        const header = document.createElement('div');
        header.style.cssText = 'padding:12px 16px;border-bottom:1px solid #ddd;font-weight:bold';
        header.textContent = title || 'Receipt';

        const frame = document.createElement('iframe');
        frame.style.cssText = 'flex:1;min-height:320px;border:0;width:100%';
        frame.srcdoc = fullHtml;

        const actions = document.createElement('div');
        actions.style.cssText = 'padding:12px;display:flex;gap:8px;justify-content:flex-end;border-top:1px solid #ddd';

        const btnPrint = document.createElement('button');
        btnPrint.type = 'button';
        btnPrint.className = 'primary';
        btnPrint.textContent = 'Print';
        btnPrint.onclick = function () {
            try {
                const fwin = frame.contentWindow;
                if (fwin) {
                    fwin.focus();
                    fwin.print();
                }
            } catch (e) {
                alert('Print failed: ' + e.message);
            }
        };

        const btnClose = document.createElement('button');
        btnClose.type = 'button';
        btnClose.textContent = 'Close';
        btnClose.onclick = function () {
            overlay.remove();
        };

        actions.appendChild(btnPrint);
        actions.appendChild(btnClose);
        panel.appendChild(header);
        panel.appendChild(frame);
        panel.appendChild(actions);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);

    }

    function printHtml(fullHtml, title, printWindow) {
        if (printWindow && !printWindow.closed) {
            try {
                printWindow.document.open();
                printWindow.document.write(fullHtml);
                printWindow.document.close();
                printWindow.focus();
                setTimeout(function () {
                    try {
                        printWindow.print();
                    } catch (e) {
                        console.error('print() in popup failed:', e);
                        showReceiptModal(fullHtml, title);
                    }
                }, 400);
                return true;
            } catch (e) {
                console.warn('Popup print failed, using modal:', e);
            }
        }
        showReceiptModal(fullHtml, title);
        return true;
    }

    function mergeStore(opts) {
        const from = (opts && opts.store) || storeSettings || {};
        const cached = storeSettings || {};
        return {
            store_name: (from.store_name || cached.store_name || 'POS').trim(),
            store_location:
                from.store_location != null
                    ? String(from.store_location)
                    : cached.store_location != null
                      ? String(cached.store_location)
                      : '',
            store_phone:
                from.store_phone != null
                    ? String(from.store_phone)
                    : cached.store_phone != null
                      ? String(cached.store_phone)
                      : '',
        };
    }

    function storeHeaderHtml(store) {
        const s = store || storeSettings || {};
        const name = (s.store_name || 'POS').trim();
        const address = (s.store_location != null ? String(s.store_location) : '').trim();
        const phone = (s.store_phone != null ? String(s.store_phone) : '').trim();
        let h = '<div class="store" style="text-align:center">' + escapeHtml(name) + '</div>';
        h += '<div style="text-align:center">' + escapeHtml(address) + '</div>';
        h += '<div style="text-align:center">Tel: ' + escapeHtml(phone) + '</div>';
        return h;
    }

    function formatDateTime(dt) {
        if (!dt) return new Date().toLocaleString();
        const d = dt instanceof Date ? dt : new Date(dt);
        return isNaN(d.getTime()) ? new Date().toLocaleString() : d.toLocaleString();
    }

    function buildSaleReceiptBody(opts) {
        const items = opts.items || [];
        const payments = opts.payments || [];
        const subtotal = Number(opts.subtotal || 0);
        const discountTotal = Number(opts.discountTotal || 0);
        const total = Number(opts.total || 0);
        let paymentTotal = 0;

        let body = storeHeaderHtml(opts.store);
        body += '<hr><div class="meta">';
        body += '<div>Sale #: ' + escapeHtml(opts.saleId) + '</div>';
        body += '<div>Date: ' + escapeHtml(formatDateTime(opts.createdAt)) + '</div>';
        if (opts.cashierName) {
            body += '<div>Cashier: ' + escapeHtml(opts.cashierName);
            if (opts.cashierRole) body += ' (' + escapeHtml(opts.cashierRole) + ')';
            body += '</div>';
        }
        if (opts.customerName) {
            body += '<div>Customer: ' + escapeHtml(opts.customerName) + '</div>';
        }
        if (opts.collectionStatus === 'to_collect') {
            body += '<div><strong>STATUS: COLLECTION PENDING</strong></div>';
        } else if (opts.collectionStatus === 'collected') {
            body += '<div><strong>STATUS: COLLECTED</strong></div>';
        }
        body += '</div><hr><div><strong>ITEMS:</strong></div><table>';

        items.forEach(function (item) {
            const qty = item.qty != null ? item.qty : item.quantity;
            const unit = Number(item.unit_price != null ? item.unit_price : item.unitPrice || 0);
            const line = Number(item.line_total != null ? item.line_total : item.lineTotal || unit * qty);
            body += '<tr><td colspan="2" class="item-name">' + escapeHtml(item.name) + '</td></tr>';
            body +=
                '<tr><td>' +
                escapeHtml(String(qty) + ' x ' + formatMoney(unit)) +
                '</td><td style="text-align:right">' +
                formatMoney(line) +
                '</td></tr>';
        });

        body += '</table><hr><table>';
        body +=
            '<tr><td>Subtotal:</td><td style="text-align:right">' + formatMoney(subtotal) + '</td></tr>';
        if (discountTotal > 0) {
            body +=
                '<tr><td>Discount:</td><td style="text-align:right">' +
                formatMoney(discountTotal) +
                '</td></tr>';
        }
        body +=
            '<tr class="total-row"><td>TOTAL:</td><td style="text-align:right">' +
            formatMoney(total) +
            '</td></tr></table><hr><div><strong>PAYMENT:</strong></div><table>';

        payments.forEach(function (p) {
            const amt = Number(p.amount || 0);
            paymentTotal += amt;
            body +=
                '<tr><td>' +
                escapeHtml(methodLabel(p.method)) +
                '</td><td style="text-align:right">' +
                formatMoney(amt) +
                '</td></tr>';
        });

        const change = paymentTotal - total;
        if (change > 0.005) {
            body +=
                '<tr class="total-row"><td>CHANGE:</td><td style="text-align:right">' +
                formatMoney(change) +
                '</td></tr>';
        }
        body += '</table><hr><div class="footer">Thank you for shopping with us!</div>';
        return body;
    }

    function printSaleReceipt(opts, printWindow) {
        opts = Object.assign({}, opts, { store: mergeStore(opts) });
        const title = 'Receipt #' + opts.saleId;
        const body = buildSaleReceiptBody(opts);
        const html = wrapReceiptHtml(title, body);
        const fallback = function () {
            printHtml(html, title, printWindow);
        };
        if (global.posWebPrint && typeof global.posWebPrint.routePrintAsync === 'function') {
            global.posWebPrint.routePrintAsync('sale', opts, printWindow, fallback).then(function (handled) {
                if (!handled) fallback();
            });
            return true;
        }
        return printHtml(html, title, printWindow);
    }

    function printWithdrawalReceipt(opts, printWindow) {
        opts = Object.assign({}, opts, { store: mergeStore(opts) });
        let body = storeHeaderHtml(opts.store);
        body += '<hr><div class="meta">';
        body += '<div>Withdrawal #: ' + escapeHtml(opts.withdrawalId) + '</div>';
        body += '<div>Receipt #: ' + escapeHtml(opts.receiptNumber || '-') + '</div>';
        body += '<div>Date: ' + escapeHtml(formatDateTime(opts.createdAt)) + '</div>';
        body += '<div>Cashier: ' + escapeHtml(opts.cashierName || '-') + '</div>';
        body += '</div><hr>';
        body += '<table><tr class="total-row"><td>Amount:</td><td style="text-align:right">' +
            formatMoney(opts.amount) + '</td></tr>';
        body += '<tr><td>Reason:</td><td style="text-align:right">' + escapeHtml(opts.reason) + '</td></tr></table>';
        if (opts.notes) {
            body += '<div style="margin-top:8px">Notes: ' + escapeHtml(opts.notes) + '</div>';
        }
        body += '<hr><div class="footer">Withdrawal receipt</div>';
        const title = 'Withdrawal ' + (opts.receiptNumber || '');
        const html = wrapReceiptHtml(title, body);
        const fallback = function () {
            printHtml(html, title, printWindow);
        };
        if (global.posWebPrint && typeof global.posWebPrint.routePrintAsync === 'function') {
            global.posWebPrint
                .routePrintAsync('withdrawal', opts, printWindow, fallback)
                .then(function (handled) {
                    if (!handled) fallback();
                });
            return true;
        }
        return printHtml(html, title, printWindow);
    }
    async function loadStoreSettings(apiFn) {
        try {
            storeSettings = await apiFn('/api/store-settings');
        } catch (e) {
            const el = document.querySelector('.shop-name');
            storeSettings = {
                store_name: (el && el.textContent.trim()) || 'POS',
                store_phone: '',
                store_location: '',
            };
        }
        return storeSettings;
    }

    function getStoreSettings() {
        return storeSettings;
    }

    function setStoreSettings(s) {
        storeSettings = s;
    }

    global.posReceipt = {
        loadStoreSettings: loadStoreSettings,
        getStoreSettings: getStoreSettings,
        setStoreSettings: setStoreSettings,
        preparePrintWindow: preparePrintWindow,
        printSaleReceipt: printSaleReceipt,
        printWithdrawalReceipt: printWithdrawalReceipt,
    };
})(typeof window !== 'undefined' ? window : global);

/**
 * ESC/POS byte builder for thermal printers (WebUSB on laptop/desktop).
 */
(function (global) {
    'use strict';

    const ESC = 0x1b;
    const GS = 0x1d;

    function enc(text) {
        const out = new Uint8Array(text.length);
        for (let i = 0; i < text.length; i++) {
            const c = text.charCodeAt(i);
            out[i] = c < 128 ? c : 0x3f;
        }
        return out;
    }

    function concat(chunks) {
        let len = 0;
        chunks.forEach(function (c) {
            len += c.length;
        });
        const out = new Uint8Array(len);
        let off = 0;
        chunks.forEach(function (c) {
            out.set(c, off);
            off += c.length;
        });
        return out;
    }

    function padMoney(n, width) {
        return Number(n || 0).toFixed(2).padStart(width || 10);
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

    function buildSale(opts, paperWidth) {
        const width = paperWidth === 48 ? 48 : 32;
        const store = opts.store || {};
        const storeName = (store.store_name || 'POS').toUpperCase();
        const chunks = [];
        chunks.push(new Uint8Array([ESC, 0x40]));
        chunks.push(new Uint8Array([ESC, 0x61, 1, ESC, 0x21, 8]));
        chunks.push(enc(storeName + '\n'));
        if (store.store_location) chunks.push(enc(String(store.store_location).slice(0, width) + '\n'));
        if (store.store_phone) chunks.push(enc('Tel: ' + String(store.store_phone).slice(0, width - 5) + '\n'));
        chunks.push(new Uint8Array([ESC, 0x21, 0, ESC, 0x61, 0]));
        chunks.push(enc('='.repeat(width) + '\n'));
        if (opts.saleId != null) chunks.push(enc('Sale #: ' + opts.saleId + '\n'));
        chunks.push(enc('Date: ' + formatDate(opts.createdAt) + '\n'));
        if (opts.cashierName) chunks.push(enc('Cashier: ' + String(opts.cashierName).slice(0, width - 9) + '\n'));
        if (opts.customerName) chunks.push(enc('Customer: ' + String(opts.customerName).slice(0, width - 10) + '\n'));
        chunks.push(new Uint8Array([ESC, 0x45, 1]));
        if (opts.collectionStatus === 'to_collect') {
            chunks.push(enc('STATUS: COLLECTION PENDING\n'));
        } else {
            chunks.push(enc('STATUS: COLLECTED\n'));
        }
        chunks.push(new Uint8Array([ESC, 0x45, 0]));
        chunks.push(enc('-'.repeat(width) + '\nITEMS:\n'));
        (opts.items || []).forEach(function (item) {
            const qty = item.qty != null ? item.qty : item.quantity;
            const unit = Number(item.unit_price != null ? item.unit_price : item.unitPrice || 0);
            const line = Number(item.line_total != null ? item.line_total : item.lineTotal || unit * qty);
            chunks.push(enc(String(item.name || 'Item').slice(0, width >= 48 ? 30 : 22) + '\n'));
            chunks.push(enc('  ' + qty + ' x ' + unit.toFixed(2) + ' = ' + line.toFixed(2) + '\n'));
        });
        chunks.push(enc('-'.repeat(width) + '\n'));
        chunks.push(enc('Subtotal:     ' + padMoney(opts.subtotal) + '\n'));
        if (Number(opts.discountTotal || 0) > 0) {
            chunks.push(enc('Discount:     ' + padMoney(opts.discountTotal) + '\n'));
        }
        chunks.push(new Uint8Array([ESC, 0x45, 1]));
        chunks.push(enc('TOTAL:        ' + padMoney(opts.total) + '\n'));
        chunks.push(new Uint8Array([ESC, 0x45, 0]));
        chunks.push(enc('='.repeat(width) + '\nPAYMENT:\n'));
        let paid = 0;
        (opts.payments || []).forEach(function (p) {
            const amt = Number(p.amount || 0);
            paid += amt;
            const label = methodLabel(p.method).slice(0, 15).padEnd(15);
            chunks.push(enc(label + ' ' + padMoney(amt) + '\n'));
        });
        const change = paid - Number(opts.total || 0);
        if (change > 0.005) {
            chunks.push(new Uint8Array([ESC, 0x45, 1]));
            chunks.push(enc('CHANGE:       ' + padMoney(change) + '\n'));
            chunks.push(new Uint8Array([ESC, 0x45, 0]));
        }
        chunks.push(enc('='.repeat(width) + '\n\n'));
        chunks.push(new Uint8Array([ESC, 0x61, 1]));
        chunks.push(enc('Thank you for shopping with us!\n'));
        chunks.push(new Uint8Array([ESC, 0x61, 0, ESC, 0x64, 3, GS, 0x56, 0x42, 3]));
        return concat(chunks);
    }

    function buildWithdrawal(opts, paperWidth) {
        const width = paperWidth === 48 ? 48 : 32;
        const store = opts.store || {};
        const storeName = (store.store_name || 'POS').toUpperCase();
        const chunks = [];
        chunks.push(new Uint8Array([ESC, 0x40]));
        chunks.push(new Uint8Array([ESC, 0x61, 1, ESC, 0x21, 8]));
        chunks.push(enc(storeName + '\n'));
        chunks.push(new Uint8Array([ESC, 0x21, 0, ESC, 0x61, 0]));
        chunks.push(enc('='.repeat(width) + '\n\n'));
        chunks.push(new Uint8Array([ESC, 0x61, 1, ESC, 0x21, 0x18]));
        chunks.push(enc('WITHDRAWAL\n'));
        chunks.push(new Uint8Array([ESC, 0x21, 0, ESC, 0x61, 0]));
        chunks.push(enc('-'.repeat(width) + '\n'));
        if (opts.receiptNumber) chunks.push(enc('Receipt #: ' + opts.receiptNumber + '\n'));
        if (opts.withdrawalId != null) chunks.push(enc('ID: ' + opts.withdrawalId + '\n'));
        chunks.push(enc('Date: ' + formatDate(opts.createdAt) + '\n'));
        if (opts.cashierName) chunks.push(enc('Cashier: ' + opts.cashierName + '\n'));
        chunks.push(enc('-'.repeat(width) + '\n'));
        chunks.push(new Uint8Array([ESC, 0x61, 1, ESC, 0x21, 0x18]));
        chunks.push(enc('AMOUNT: ' + Number(opts.amount || 0).toFixed(2) + '\n'));
        chunks.push(new Uint8Array([ESC, 0x21, 0, ESC, 0x61, 0]));
        chunks.push(enc('Reason: ' + String(opts.reason || '') + '\n'));
        if (opts.notes) chunks.push(enc('Notes: ' + opts.notes + '\n'));
        chunks.push(enc('='.repeat(width) + '\n'));
        chunks.push(new Uint8Array([ESC, 0x64, 3, GS, 0x56, 0x42, 3]));
        return concat(chunks);
    }

    function formatDate(dt) {
        const d = dt ? new Date(dt) : new Date();
        return isNaN(d.getTime()) ? new Date().toLocaleString() : d.toLocaleString();
    }

    function getPaperWidth() {
        try {
            const w = parseInt(localStorage.getItem('pos_paper_width') || '32', 10);
            return w >= 48 ? 48 : 32;
        } catch (e) {
            return 32;
        }
    }

    global.posEscPos = {
        buildSale: buildSale,
        buildWithdrawal: buildWithdrawal,
        getPaperWidth: getPaperWidth,
        setPaperWidth: function (w) {
            localStorage.setItem('pos_paper_width', w >= 48 ? '48' : '32');
        },
    };
})(typeof window !== 'undefined' ? window : global);

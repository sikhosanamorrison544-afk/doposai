/**
 * Expense ledger page — create approved operating expenses; list/filter/approve.
 */
(function () {
    'use strict';

    function token() {
        try {
            return localStorage.getItem('pos_token') || '';
        } catch (e) {
            return '';
        }
    }

    function authHeaders() {
        const t = token();
        const h = { 'Content-Type': 'application/json', Accept: 'application/json' };
        if (t) h.Authorization = 'Bearer ' + t;
        return h;
    }

    let currencyCode = 'USD';

    function money(n) {
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency',
                currency: currencyCode || 'USD',
                minimumFractionDigits: 2,
            }).format(Number(n) || 0);
        } catch (e) {
            return (currencyCode || 'USD') + ' ' + (Number(n) || 0).toFixed(2);
        }
    }

    async function api(path, opts) {
        const res = await fetch(path, Object.assign({ headers: authHeaders(), cache: 'no-store' }, opts || {}));
        if (res.status === 401) {
            window.location.href = '/login';
            throw new Error('Unauthorized');
        }
        const text = await res.text();
        let data = null;
        try {
            data = text ? JSON.parse(text) : null;
        } catch (e) {
            data = { detail: text };
        }
        if (!res.ok) {
            const detail = (data && data.detail) || res.statusText;
            throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
        }
        return data;
    }

    async function loadCurrency() {
        try {
            const s = await api('/api/store-settings');
            if (s && s.currency) currencyCode = s.currency;
        } catch (e) { /* keep USD */ }
    }

    async function loadCategories() {
        const sel = document.getElementById('expense-category');
        if (!sel) return;
        const cats = await api('/api/expenses/categories');
        sel.innerHTML = '';
        (cats || []).forEach(function (c) {
            const opt = document.createElement('option');
            opt.value = c.value;
            opt.textContent = c.label;
            sel.appendChild(opt);
        });
    }

    function setMsg(text, isError) {
        const el = document.getElementById('expense-message');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = isError ? '#b91c1c' : '#166534';
    }

    async function loadList() {
        const body = document.getElementById('expenses-body');
        if (!body) return;
        const status = (document.getElementById('expense-filter-status') || {}).value || '';
        const q = status ? ('?status=' + encodeURIComponent(status)) : '';
        const rows = await api('/api/expenses' + q);
        body.innerHTML = '';
        if (!rows || !rows.length) {
            body.innerHTML = '<tr><td colspan="6">No expenses found.</td></tr>';
            return;
        }
        rows.forEach(function (e) {
            const tr = document.createElement('tr');
            const d = (e.expense_date || '').slice(0, 10);
            const actions = [];
            if (e.status === 'draft' || e.status === 'pending') {
                actions.push(
                    '<button type="button" class="small" data-approve="' + e.id + '">Approve</button>'
                );
            }
            if (e.status === 'approved' || e.status === 'draft' || e.status === 'pending') {
                actions.push(
                    '<button type="button" class="small" data-void="' + e.id + '">Void</button>'
                );
            }
            tr.innerHTML =
                '<td>' + d + '</td>' +
                '<td>' + (e.category_label || e.category) + '</td>' +
                '<td>' + escapeHtml(e.description) + '</td>' +
                '<td style="text-align:right;">' + money(e.amount) + '</td>' +
                '<td><span class="expense-status ' + e.status + '">' + e.status + '</span></td>' +
                '<td>' + actions.join(' ') + '</td>';
            body.appendChild(tr);
        });
        body.querySelectorAll('[data-approve]').forEach(function (btn) {
            btn.addEventListener('click', async function () {
                try {
                    await api('/api/expenses/' + btn.getAttribute('data-approve') + '/approve', {
                        method: 'POST',
                        body: '{}',
                    });
                    await loadList();
                } catch (err) {
                    alert(err.message || 'Approve failed');
                }
            });
        });
        body.querySelectorAll('[data-void]').forEach(function (btn) {
            btn.addEventListener('click', async function () {
                if (!confirm('Void this expense?')) return;
                try {
                    await api('/api/expenses/' + btn.getAttribute('data-void') + '/void', {
                        method: 'POST',
                        body: JSON.stringify({ reason: 'voided from UI' }),
                    });
                    await loadList();
                } catch (err) {
                    alert(err.message || 'Void failed');
                }
            });
        });
    }

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function onSubmit(ev) {
        ev.preventDefault();
        setMsg('');
        const dateEl = document.getElementById('expense-date');
        const payload = {
            amount: parseFloat(document.getElementById('expense-amount').value),
            category: document.getElementById('expense-category').value,
            description: document.getElementById('expense-description').value.trim(),
            payment_method: document.getElementById('expense-method').value,
            supplier_or_payee: document.getElementById('expense-payee').value.trim() || null,
            reference: document.getElementById('expense-reference').value.trim() || null,
            notes: document.getElementById('expense-notes').value.trim() || null,
            auto_approve: true,
        };
        if (dateEl && dateEl.value) {
            payload.expense_date = dateEl.value + 'T12:00:00';
        }
        try {
            await api('/api/expenses', { method: 'POST', body: JSON.stringify(payload) });
            setMsg('Expense saved and approved.');
            document.getElementById('expense-form').reset();
            if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
            await loadList();
        } catch (err) {
            setMsg(err.message || 'Save failed', true);
        }
    }

    document.addEventListener('DOMContentLoaded', async function () {
        if (!token()) {
            window.location.href = '/login';
            return;
        }
        const dateEl = document.getElementById('expense-date');
        if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
        document.getElementById('expense-form').addEventListener('submit', onSubmit);
        document.getElementById('btn-refresh-expenses').addEventListener('click', function () {
            loadList().catch(function (e) { alert(e.message); });
        });
        document.getElementById('expense-filter-status').addEventListener('change', function () {
            loadList().catch(function (e) { alert(e.message); });
        });
        try {
            await loadCurrency();
            await loadCategories();
            await loadList();
        } catch (e) {
            setMsg(e.message || 'Failed to load expenses', true);
        }
    });
})();

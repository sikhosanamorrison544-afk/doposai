/**
 * Enterprise module UI: suppliers, POs, adjustments, branches, reorder, audit.
 */
(function () {
    'use strict';

    const API = '/api/enterprise';
    let cachedSuppliers = [];
    let cachedProducts = [];
    let cachedBranches = [];

    async function api(path, options) {
        const token = localStorage.getItem('pos_token') || sessionStorage.getItem('pos_token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = 'Bearer ' + token;
        const res = await fetch(API + path, { ...options, headers: { ...headers, ...(options && options.headers) } });
        if (res.status === 401) {
            window.location.href = '/';
            throw new Error('Unauthorized');
        }
        if (res.status === 202) {
            const queued = await res.json().catch(() => ({}));
            if (queued.offline_queued) {
                alert('Saved offline — will sync when you are back online.');
                return queued;
            }
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || res.statusText);
        }
        if (res.headers.get('content-type')?.includes('application/json')) return res.json();
        return res;
    }

    async function apiRoot(path, options) {
        const token = localStorage.getItem('pos_token') || sessionStorage.getItem('pos_token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = 'Bearer ' + token;
        const res = await fetch(path, { ...options, headers: { ...headers, ...(options && options.headers) } });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
        return res.json();
    }

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function initTabs() {
        document.querySelectorAll('.enterprise-tabs button').forEach((btn) => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                document.querySelectorAll('.enterprise-tabs button').forEach((b) => b.classList.toggle('active', b === btn));
                document.querySelectorAll('.enterprise-panel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + tab));
                if (tab === 'purchasing') loadPOs();
                if (tab === 'inventory') loadInventory();
                if (tab === 'branches') loadBranches();
                if (tab === 'reorder') loadReorder();
                if (tab === 'audit') loadAudit();
                if (tab === 'statements') loadStatementCustomers();
            });
        });
    }

    async function loadDashboard() {
        try {
            const d = await api('/dashboards/summary');
            const el = document.getElementById('dashboard-stats');
            if (!el) return;
            const cards = [];
            if (d.suppliers != null) cards.push(['Suppliers', d.suppliers]);
            if (d.open_purchase_orders != null) cards.push(['Open POs', d.open_purchase_orders]);
            if (d.pending_adjustments != null) cards.push(['Pending adjustments', d.pending_adjustments]);
            if (d.branches != null) cards.push(['Branches', d.branches]);
            if (d.transfers_in_transit != null) cards.push(['Transfers in transit', d.transfers_in_transit]);
            el.innerHTML = cards.map(([l, v]) => `<div class="enterprise-card"><strong>${esc(l)}</strong><div style="font-size:1.5rem">${esc(v)}</div></div>`).join('');
        } catch (e) {
            console.warn('Dashboard', e);
        }
    }

    async function loadSuppliers(q) {
        const qs = q ? '?q=' + encodeURIComponent(q) : '';
        const rows = await api('/suppliers' + qs);
        const tbody = document.getElementById('suppliers-tbody');
        if (!tbody) return;
        tbody.innerHTML = rows.map((s) => `
            <tr>
                <td>${esc(s.business_name)}</td>
                <td>${esc(s.contact_person)}</td>
                <td>${esc(s.phone)}</td>
                <td>${Number(s.balance).toFixed(2)}</td>
                <td><button type="button" data-edit="${s.id}">Edit</button>
                    <a href="${API}/suppliers/${s.id}/ledger" target="_blank">Ledger</a></td>
            </tr>`).join('');
        tbody.querySelectorAll('[data-edit]').forEach((btn) => {
            btn.addEventListener('click', () => editSupplier(Number(btn.dataset.edit), rows));
        });
    }

    function showSupplierForm(data) {
        document.getElementById('supplier-form-card').style.display = 'block';
        document.getElementById('supplier-form-title').textContent = data ? 'Edit supplier' : 'New supplier';
        document.getElementById('supplier-id').value = data ? data.id : '';
        document.getElementById('sup-business-name').value = data?.business_name || '';
        document.getElementById('sup-contact').value = data?.contact_person || '';
        document.getElementById('sup-phone').value = data?.phone || '';
        document.getElementById('sup-whatsapp').value = data?.whatsapp_number || '';
        document.getElementById('sup-email').value = data?.email || '';
        document.getElementById('sup-city').value = data?.city || '';
        document.getElementById('sup-notes').value = data?.notes || '';
    }

    async function editSupplier(id, cache) {
        let s = cache?.find((x) => x.id === id);
        if (!s) s = await api('/suppliers/' + id);
        showSupplierForm(s);
    }

    async function saveSupplier(e) {
        e.preventDefault();
        const id = document.getElementById('supplier-id').value;
        const body = {
            business_name: document.getElementById('sup-business-name').value.trim(),
            contact_person: document.getElementById('sup-contact').value.trim() || null,
            phone: document.getElementById('sup-phone').value.trim() || null,
            whatsapp_number: document.getElementById('sup-whatsapp').value.trim() || null,
            email: document.getElementById('sup-email').value.trim() || null,
            city: document.getElementById('sup-city').value.trim() || null,
            notes: document.getElementById('sup-notes').value.trim() || null,
        };
        if (id) await api('/suppliers/' + id, { method: 'PUT', body: JSON.stringify(body) });
        else await api('/suppliers', { method: 'POST', body: JSON.stringify(body) });
        document.getElementById('supplier-form-card').style.display = 'none';
        loadSuppliers(document.getElementById('supplier-search')?.value);
    }

    async function ensurePoLookups() {
        if (!cachedSuppliers.length) cachedSuppliers = await api('/suppliers');
        if (!cachedProducts.length) cachedProducts = await apiRoot('/api/products');
        if (!cachedBranches.length) {
            try { cachedBranches = await api('/branches'); } catch (_) { cachedBranches = []; }
        }
    }

    function supplierName(id) {
        const s = cachedSuppliers.find((x) => x.id === id);
        return s ? s.business_name : '#' + id;
    }

    async function loadPOs() {
        await ensurePoLookups();
        const rows = await api('/purchase-orders');
        const tbody = document.getElementById('po-tbody');
        if (!tbody) return;
        tbody.innerHTML = rows.map((p) => `
            <tr>
                <td><button type="button" class="link-btn" data-po-view="${p.id}">${esc(p.po_number)}</button></td>
                <td>${esc(supplierName(p.supplier_id))}</td>
                <td>${esc(p.status)}</td>
                <td>${Number(p.total).toFixed(2)}</td>
                <td>
                    <a href="${API}/purchase-orders/${p.id}/pdf" target="_blank">PDF</a>
                    ${p.status === 'draft' ? ` · <button type="button" data-po-edit="${p.id}">Edit</button>` : ''}
                </td>
            </tr>`).join('');
        tbody.querySelectorAll('[data-po-view]').forEach((b) => b.addEventListener('click', () => showPoDetail(Number(b.dataset.poView))));
        tbody.querySelectorAll('[data-po-edit]').forEach((b) => b.addEventListener('click', () => editPo(Number(b.dataset.poEdit))));
    }

    function addPoLineRow(productId, qty, cost) {
        const tbody = document.getElementById('po-lines-tbody');
        if (!tbody) return;
        const tr = document.createElement('tr');
        const opts = cachedProducts.map((p) =>
            `<option value="${p.id}" data-cost="${p.cost_price}" ${p.id === productId ? 'selected' : ''}>${esc(p.name)}</option>`
        ).join('');
        tr.innerHTML = `
            <td><select class="po-line-product" required><option value="">Select…</option>${opts}</select></td>
            <td><input type="number" class="po-line-qty" min="0.01" step="0.01" value="${qty || 1}"></td>
            <td><input type="number" class="po-line-cost" min="0" step="0.01" value="${cost || 0}"></td>
            <td><button type="button" class="po-line-remove">✕</button></td>`;
        tr.querySelector('.po-line-product')?.addEventListener('change', (e) => {
            const opt = e.target.selectedOptions[0];
            if (opt?.dataset.cost) tr.querySelector('.po-line-cost').value = opt.dataset.cost;
        });
        tr.querySelector('.po-line-remove')?.addEventListener('click', () => tr.remove());
        tbody.appendChild(tr);
    }

    async function showPoForm(editId) {
        await ensurePoLookups();
        document.getElementById('po-detail-card').style.display = 'none';
        document.getElementById('po-form-card').style.display = 'block';
        document.getElementById('po-form-title').textContent = editId ? 'Edit purchase order' : 'New purchase order';
        document.getElementById('po-edit-id').value = editId || '';
        const supSel = document.getElementById('po-supplier');
        supSel.innerHTML = cachedSuppliers.map((s) => `<option value="${s.id}">${esc(s.business_name)}</option>`).join('');
        const brSel = document.getElementById('po-branch');
        brSel.innerHTML = '<option value="">— Default —</option>' +
            cachedBranches.map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join('');
        document.getElementById('po-notes').value = '';
        document.getElementById('po-lines-tbody').innerHTML = '';
        if (editId) {
            const po = await api('/purchase-orders/' + editId);
            supSel.value = po.supplier_id;
            brSel.value = po.branch_id || '';
            document.getElementById('po-notes').value = po.notes || '';
            po.items.forEach((it) => addPoLineRow(it.product_id, it.quantity_ordered, it.unit_cost));
        } else {
            addPoLineRow();
        }
    }

    async function editPo(id) {
        await showPoForm(id);
    }

    function collectPoLines() {
        const items = [];
        document.querySelectorAll('#po-lines-tbody tr').forEach((tr) => {
            const pid = Number(tr.querySelector('.po-line-product')?.value);
            const qty = parseFloat(tr.querySelector('.po-line-qty')?.value);
            const cost = parseFloat(tr.querySelector('.po-line-cost')?.value);
            if (pid && qty > 0) items.push({ product_id: pid, quantity_ordered: qty, unit_cost: cost });
        });
        return items;
    }

    async function savePo(e) {
        e.preventDefault();
        const items = collectPoLines();
        if (!items.length) { alert('Add at least one line item'); return; }
        const body = {
            supplier_id: Number(document.getElementById('po-supplier').value),
            branch_id: document.getElementById('po-branch').value ? Number(document.getElementById('po-branch').value) : null,
            notes: document.getElementById('po-notes').value.trim() || null,
            items,
        };
        const editId = document.getElementById('po-edit-id').value;
        if (editId) await api('/purchase-orders/' + editId, { method: 'PUT', body: JSON.stringify(body) });
        else await api('/purchase-orders', { method: 'POST', body: JSON.stringify(body) });
        document.getElementById('po-form-card').style.display = 'none';
        loadPOs();
    }

    async function poAction(id, action) {
        await api('/purchase-orders/' + id + '/' + action, { method: 'POST', body: '{}' });
        showPoDetail(id);
        loadPOs();
        loadDashboard();
    }

    async function receivePoPartial(id) {
        const items = [];
        document.querySelectorAll('#po-receive-tbody tr').forEach((tr) => {
            const itemId = Number(tr.dataset.itemId);
            const qty = parseFloat(tr.querySelector('.po-recv-qty')?.value);
            if (itemId && qty > 0) items.push({ item_id: itemId, quantity_received: qty });
        });
        if (!items.length) {
            alert('Enter quantity to receive on at least one line');
            return;
        }
        await api('/purchase-orders/' + id + '/receive', { method: 'POST', body: JSON.stringify({ items }) });
        showPoDetail(id);
        loadPOs();
        loadDashboard();
    }

    async function receivePoFull(id, items) {
        const payload = {
            items: items
                .map((it) => {
                    const remaining = Math.max(0, Number(it.quantity_ordered) - Number(it.quantity_received));
                    return remaining > 0 ? { item_id: it.id, quantity_received: remaining } : null;
                })
                .filter(Boolean),
        };
        if (!payload.items.length) return;
        await api('/purchase-orders/' + id + '/receive', { method: 'POST', body: JSON.stringify(payload) });
        showPoDetail(id);
        loadPOs();
        loadDashboard();
    }

    function canReceivePo(status) {
        return ['approved', 'partially_received', 'sent'].includes(status);
    }

    async function showPoDetail(id) {
        document.getElementById('po-form-card').style.display = 'none';
        const card = document.getElementById('po-detail-card');
        card.style.display = 'block';
        const po = await api('/purchase-orders/' + id);
        document.getElementById('po-detail-title').textContent = po.po_number + ' — ' + po.status;
        const showReceive = canReceivePo(po.status);
        const lines = po.items.map((it) => {
            const remaining = Math.max(0, Number(it.quantity_ordered) - Number(it.quantity_received));
            const recvCell = showReceive && remaining > 0
                ? `<input type="number" class="po-recv-qty" min="0" max="${remaining}" step="0.01" value="${remaining}" style="width:80px">`
                : `${it.quantity_received}/${it.quantity_ordered}`;
            return `<tr data-item-id="${it.id}"><td>${esc(it.product_name)}</td><td>${recvCell}</td><td>${Number(it.unit_cost).toFixed(2)}</td></tr>`;
        }).join('');
        const receiveTable = showReceive
            ? `<h4>Receive stock</h4>
               <table class="enterprise-table"><thead><tr><th>Product</th><th>Qty to receive</th><th>Cost</th></tr></thead>
               <tbody id="po-receive-tbody">${lines}</tbody></table>`
            : `<table class="enterprise-table"><thead><tr><th>Product</th><th>Recv/Ord</th><th>Cost</th></tr></thead><tbody>${lines}</tbody></table>`;
        document.getElementById('po-detail-body').innerHTML = `
            <p>Supplier: ${esc(supplierName(po.supplier_id))}</p>
            <p>Total: ${Number(po.total).toFixed(2)}</p>
            ${receiveTable}`;
        const actions = document.getElementById('po-detail-actions');
        const btns = [];
        if (po.status === 'draft') btns.push(`<button type="button" data-act="send">Send</button>`, `<button type="button" data-act="edit">Edit</button>`);
        if (po.status === 'sent' || po.status === 'draft') btns.push(`<button type="button" data-act="approve">Approve</button>`);
        if (showReceive) {
            btns.push(`<button type="button" data-act="receive-partial">Receive selected</button>`);
            btns.push(`<button type="button" data-act="receive-all">Receive all remaining</button>`);
        }
        if (po.status !== 'received' && po.status !== 'cancelled') btns.push(`<button type="button" data-act="cancel">Cancel</button>`);
        btns.push(`<a href="${API}/purchase-orders/${id}/pdf" target="_blank">PDF</a>`);
        actions.innerHTML = btns.join(' ');
        actions.querySelector('[data-act="send"]')?.addEventListener('click', () => poAction(id, 'send'));
        actions.querySelector('[data-act="approve"]')?.addEventListener('click', () => poAction(id, 'approve'));
        actions.querySelector('[data-act="cancel"]')?.addEventListener('click', () => poAction(id, 'cancel'));
        actions.querySelector('[data-act="edit"]')?.addEventListener('click', () => editPo(id));
        actions.querySelector('[data-act="receive-all"]')?.addEventListener('click', () => receivePoFull(id, po.items));
        actions.querySelector('[data-act="receive-partial"]')?.addEventListener('click', () => receivePoPartial(id));
    }

    let stmtCustomerId = null;
    let lastStatementData = null;

    async function loadStatementCustomers() {
        const customers = await apiRoot('/api/customers');
        const sel = document.getElementById('stmt-customer');
        if (!sel) return;
        sel.innerHTML = '<option value="">Select customer…</option>' +
            customers.map((c) => `<option value="${c.id}">${esc(c.name)}${c.phone ? ' (' + esc(c.phone) + ')' : ''}</option>`).join('');
    }

    async function loadStatement() {
        const id = Number(document.getElementById('stmt-customer')?.value);
        if (!id) return;
        stmtCustomerId = id;
        const data = await api('/customers/' + id + '/statement');
        lastStatementData = data;
        document.getElementById('stmt-summary').innerHTML =
            `<strong>${esc(data.customer_name)}</strong> · Balance: <strong>${Number(data.balance).toFixed(2)}</strong>` +
            (data.customer_email ? ` · ${esc(data.customer_email)}` : '');
        const tbody = document.getElementById('stmt-tbody');
        tbody.innerHTML = (data.lines || []).map((l) =>
            `<tr><td>${esc(l.date)}</td><td>${esc(l.type)}</td><td>${l.amount}</td><td>${esc(l.detail || '')}</td></tr>`
        ).join('');
        const pdfLink = document.getElementById('stmt-pdf-link');
        pdfLink.href = API + '/customers/' + id + '/statement/pdf';
        pdfLink.style.display = 'inline';
        document.getElementById('btn-stmt-email').style.display = 'inline';
    }

    async function emailStatement() {
        if (!stmtCustomerId) return;
        const defaultTo = lastStatementData?.customer_email || '';
        const to = prompt('Send statement to email:', defaultTo);
        if (to === null) return;
        const body = to.trim() ? { to_email: to.trim() } : {};
        await api('/customers/' + stmtCustomerId + '/statement/email', { method: 'POST', body: JSON.stringify(body) });
        alert('Statement emailed successfully.');
    }

    async function loadInventory() {
        const adj = await api('/adjustments');
        const tbody = document.getElementById('adj-tbody');
        if (tbody) {
            tbody.innerHTML = adj.map((a) => `
                <tr><td>${esc(a.adjustment_type)}</td><td>${a.product_id}</td>
                <td>${a.quantity_change}</td><td>${esc(a.status)}</td>
                <td>${a.status === 'pending' ? '<button data-approve="' + a.id + '">Approve</button>' : ''}</td></tr>`).join('');
            tbody.querySelectorAll('[data-approve]').forEach((b) => {
                b.addEventListener('click', async () => {
                    await api('/adjustments/' + b.dataset.approve + '/approve', { method: 'POST' });
                    loadInventory();
                });
            });
        }
        const transfers = await api('/transfers');
        const tt = document.getElementById('transfer-tbody');
        if (tt) {
            tt.innerHTML = transfers.map((t) => `
                <tr><td>${esc(t.transfer_number)}</td><td>${t.from_branch_id}</td>
                <td>${t.to_branch_id}</td><td>${esc(t.status)}</td></tr>`).join('');
        }
    }

    async function loadBranches() {
        const rows = await api('/branches');
        cachedBranches = rows;
        const tbody = document.getElementById('branches-tbody');
        if (!tbody) return;
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="opacity:0.7;">No branches yet — click <strong>Add branch</strong> above.</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map((b) => `
            <tr>
                <td>${esc(b.name)}</td>
                <td>${esc(b.code || '—')}</td>
                <td>${esc(b.phone || '—')}</td>
                <td>${b.is_default ? 'Yes' : ''}</td>
            </tr>`).join('');
    }

    function showBranchForm() {
        const card = document.getElementById('branch-form-card');
        const msg = document.getElementById('branch-form-msg');
        if (!card) return;
        document.getElementById('branch-name').value = '';
        document.getElementById('branch-code').value = '';
        document.getElementById('branch-address').value = '';
        document.getElementById('branch-phone').value = '';
        document.getElementById('branch-is-default').checked = cachedBranches.length === 0;
        if (msg) msg.textContent = '';
        card.style.display = 'block';
        document.getElementById('branch-name')?.focus();
    }

    async function saveBranch(ev) {
        ev.preventDefault();
        const msg = document.getElementById('branch-form-msg');
        const name = document.getElementById('branch-name').value.trim();
        if (!name) {
            if (msg) msg.textContent = 'Branch name is required.';
            return;
        }
        const payload = {
            name: name,
            code: document.getElementById('branch-code').value.trim() || null,
            address: document.getElementById('branch-address').value.trim() || null,
            phone: document.getElementById('branch-phone').value.trim() || null,
            is_default: document.getElementById('branch-is-default').checked,
        };
        try {
            await api('/branches', { method: 'POST', body: JSON.stringify(payload) });
            document.getElementById('branch-form-card').style.display = 'none';
            await loadBranches();
        } catch (e) {
            if (msg) msg.textContent = e.message || 'Could not save branch.';
        }
    }

    async function loadReorder() {
        const rows = await api('/reorder-suggestions?days=30');
        const tbody = document.getElementById('reorder-tbody');
        if (!tbody) return;
        tbody.innerHTML = rows.map((r) => `
            <tr><td>${esc(r.product_name)}</td><td>${r.current_stock}</td>
            <td>${r.avg_weekly_sales}</td><td><strong>${r.suggested_reorder}</strong></td></tr>`).join('');
    }

    async function loadAudit() {
        const rows = await api('/audit-logs?limit=100');
        const tbody = document.getElementById('audit-tbody');
        if (!tbody) return;
        tbody.innerHTML = rows.map((r) => `
            <tr><td>${esc(r.created_at)}</td><td>${esc(r.username)}</td>
            <td>${esc(r.action)}</td><td>${esc(r.entity_type)} #${r.entity_id || ''}</td></tr>`).join('');
    }

    document.addEventListener('DOMContentLoaded', () => {
        initTabs();
        loadDashboard();
        loadSuppliers();
        const search = document.getElementById('supplier-search');
        if (search) {
            let t;
            search.addEventListener('input', () => {
                clearTimeout(t);
                t = setTimeout(() => loadSuppliers(search.value), 300);
            });
        }
        document.getElementById('btn-supplier-add')?.addEventListener('click', () => showSupplierForm(null));
        document.getElementById('btn-supplier-cancel')?.addEventListener('click', () => {
            document.getElementById('supplier-form-card').style.display = 'none';
        });
        document.getElementById('supplier-form')?.addEventListener('submit', saveSupplier);
        document.getElementById('btn-po-refresh')?.addEventListener('click', loadPOs);
        document.getElementById('btn-po-new')?.addEventListener('click', () => showPoForm(null));
        document.getElementById('btn-po-cancel')?.addEventListener('click', () => {
            document.getElementById('po-form-card').style.display = 'none';
        });
        document.getElementById('btn-po-add-line')?.addEventListener('click', () => addPoLineRow());
        document.getElementById('po-form')?.addEventListener('submit', savePo);
        document.getElementById('btn-stmt-load')?.addEventListener('click', loadStatement);
        document.getElementById('btn-stmt-email')?.addEventListener('click', emailStatement);
        document.getElementById('btn-branch-add')?.addEventListener('click', showBranchForm);
        document.getElementById('btn-branch-cancel')?.addEventListener('click', () => {
            document.getElementById('branch-form-card').style.display = 'none';
        });
        document.getElementById('branch-form')?.addEventListener('submit', saveBranch);
    });
})();

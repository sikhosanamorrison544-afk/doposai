let refundsToken = null;
let refundsUser = null;
let allRefunds = [];
let saleSummary = null;
let userPermissions = [];

function escapeHtml(text) {
    if (text == null || text === '') return '-';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function formatMoney(n) {
    const v = Number(n);
    return '$' + (isNaN(v) ? '0.00' : v.toFixed(2));
}

function formatDate(iso) {
    if (!iso) return '-';
    try {
        return new Date(iso).toLocaleString();
    } catch (_) {
        return iso;
    }
}

async function ensureAuthenticated() {
    const savedToken = localStorage.getItem('pos_token');
    const savedUser = localStorage.getItem('pos_user');
    if (!savedToken || !savedUser) {
        window.location.href = '/';
        return false;
    }
    refundsToken = savedToken.trim();
    refundsUser = JSON.parse(savedUser);
    const el = document.getElementById('refunds-user-info');
    if (el) el.textContent = `${refundsUser.username} (${refundsUser.role})`;
    try {
        const me = await refundsApi('/api/auth/me');
        userPermissions = me.permissions || [];
    } catch (_) {
        userPermissions = [];
    }
    return true;
}

async function refundsApi(path, options = {}) {
    if (!refundsToken) {
        const ok = await ensureAuthenticated();
        if (!ok) throw new Error('Not authenticated');
    }
    const headers = Object.assign({}, options.headers || {}, {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + refundsToken,
    });
    const res = await fetch(path, Object.assign({}, options, { headers }));
    if (!res.ok) {
        const text = await res.text();
        let msg = text;
        try {
            const j = JSON.parse(text);
            msg = j.detail || j.message || text;
        } catch (_) {}
        if (res.status === 401) {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
            return;
        }
        throw new Error(msg || res.statusText);
    }
    if (res.status === 204) return null;
    return res.json();
}

function hasPerm(name) {
    return userPermissions.indexOf(name) >= 0;
}

function canApprove() {
    return hasPerm('approve_refunds') || (window.PosRoles && PosRoles.isSupervisorOrAdmin(refundsUser));
}

async function loadRefunds() {
    const body = document.getElementById('refunds-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;">Loading…</td></tr>';
    try {
        allRefunds = await refundsApi('/api/refunds?limit=500');
        filterAndRenderRefunds();
    } catch (e) {
        body.innerHTML = `<tr><td colspan="8" style="color:#ef4444;text-align:center;padding:24px;">${escapeHtml(e.message)}</td></tr>`;
    }
}

function updateStats(list) {
    const pending = list.filter((r) => r.status === 'pending');
    const approved = list.filter((r) => r.status === 'approved');
    const approvedAmt = approved.reduce((s, r) => s + Number(r.amount || 0), 0);
    document.getElementById('stat-total').textContent = String(list.length);
    document.getElementById('stat-pending').textContent = String(pending.length);
    document.getElementById('stat-approved').textContent = String(approved.length);
    document.getElementById('stat-approved-amt').textContent = formatMoney(approvedAmt);
}

function filterAndRenderRefunds() {
    const status = (document.getElementById('filter-status') || {}).value || '';
    const search = ((document.getElementById('refund-search') || {}).value || '').toLowerCase();
    let list = allRefunds.slice();
    if (status) list = list.filter((r) => r.status === status);
    if (search) {
        list = list.filter(
            (r) =>
                String(r.refund_number).toLowerCase().includes(search) ||
                String(r.sale_id).includes(search) ||
                (r.reason && r.reason.toLowerCase().includes(search)) ||
                (r.requested_by_name && r.requested_by_name.toLowerCase().includes(search))
        );
    }
    updateStats(allRefunds);
    const body = document.getElementById('refunds-body');
    if (!list.length) {
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;opacity:0.7;">No refunds found.</td></tr>';
        return;
    }
    body.innerHTML = list
        .map((r) => {
            let actions = '';
            if (r.status === 'pending' && canApprove()) {
                actions =
                    `<button type="button" class="small primary" data-approve="${r.id}">Approve</button> ` +
                    `<button type="button" class="small danger" data-reject="${r.id}">Reject</button>`;
            } else if (r.items && r.items.length) {
                actions = r.items.map((i) => escapeHtml(i.product_name) + ' ×' + i.quantity).join(', ');
            }
            const statusCls = 'status-' + r.status;
            return `<tr style="border-bottom:1px solid rgba(255,255,255,0.08);">
                <td style="padding:10px;">${formatDate(r.created_at)}</td>
                <td style="padding:10px;">${escapeHtml(r.refund_number)}</td>
                <td style="padding:10px;">#${r.sale_id}</td>
                <td style="padding:10px;text-align:right;">${formatMoney(r.amount)}</td>
                <td style="padding:10px;" class="${statusCls}">${escapeHtml(r.status)}</td>
                <td style="padding:10px;">${escapeHtml(r.requested_by_name)}</td>
                <td style="padding:10px;">${escapeHtml(r.reason)}</td>
                <td style="padding:10px;">${actions}</td>
            </tr>`;
        })
        .join('');
}

async function loadSaleForRefund() {
    const saleId = Number(document.getElementById('refund-sale-id').value);
    const msg = document.getElementById('create-refund-msg');
    const preview = document.getElementById('sale-preview');
    const wrap = document.getElementById('sale-items-wrap');
    const submitBtn = document.getElementById('btn-submit-refund');
    msg.style.display = 'none';
    if (!saleId || saleId < 1) {
        msg.textContent = 'Enter a valid sale ID.';
        msg.style.display = 'block';
        return;
    }
    try {
        saleSummary = await refundsApi('/api/sales/' + saleId + '/refund-summary');
        if (saleSummary.fully_refunded) {
            preview.innerHTML = `<p style="color:#f59e0b;">Sale #${saleId} is fully refunded — nothing left to refund.</p>`;
            preview.style.display = 'block';
            wrap.style.display = 'none';
            submitBtn.disabled = true;
            return;
        }
        preview.innerHTML =
            `<strong>Sale #${saleSummary.sale_id}</strong> — ${formatDate(saleSummary.created_at)} — ` +
            `Cashier: ${escapeHtml(saleSummary.cashier_name)} — Total: ${formatMoney(saleSummary.total)}`;
        preview.style.display = 'block';
        const tbody = document.getElementById('sale-items-body');
        tbody.innerHTML = saleSummary.items
            .filter((i) => i.quantity_remaining > 0)
            .map(
                (i) => `<tr data-sale-item-id="${i.sale_item_id}">
                    <td>${escapeHtml(i.product_name)}</td>
                    <td>${i.quantity_sold}</td>
                    <td>${i.quantity_refunded}</td>
                    <td><input type="number" min="0" max="${i.quantity_remaining}" value="0" class="refund-qty-input"></td>
                    <td>${formatMoney(i.line_total)}</td>
                </tr>`
            )
            .join('');
        wrap.style.display = 'block';
        submitBtn.disabled = false;
    } catch (e) {
        saleSummary = null;
        preview.innerHTML = `<p style="color:#ef4444;">${escapeHtml(e.message)}</p>`;
        preview.style.display = 'block';
        wrap.style.display = 'none';
        submitBtn.disabled = true;
    }
}

async function submitRefund() {
    const msg = document.getElementById('create-refund-msg');
    const submitBtn = document.getElementById('btn-submit-refund');
    if (!saleSummary) {
        msg.textContent = 'Load a sale first.';
        msg.style.display = 'block';
        return;
    }
    const reason = document.getElementById('refund-reason').value.trim();
    const refundMethod = document.getElementById('refund-method').value;
    const notes = document.getElementById('refund-notes').value.trim() || null;
    const fullRefund = document.getElementById('refund-full').checked;
    if (!reason) {
        msg.textContent = 'Reason is required.';
        msg.style.display = 'block';
        return;
    }
    const items = [];
    if (!fullRefund) {
        document.querySelectorAll('#sale-items-body tr').forEach((row) => {
            const saleItemId = Number(row.getAttribute('data-sale-item-id'));
            const qty = Number(row.querySelector('.refund-qty-input').value);
            if (qty > 0) items.push({ sale_item_id: saleItemId, quantity: qty });
        });
        if (!items.length) {
            msg.textContent = 'Enter refund quantity for at least one item, or check Full refund.';
            msg.style.display = 'block';
            return;
        }
    }
    submitBtn.disabled = true;
    msg.textContent = 'Submitting…';
    msg.style.display = 'block';
    try {
        const payload = {
            sale_id: saleSummary.sale_id,
            reason: reason,
            refund_method: refundMethod,
            notes: notes,
            full_refund: fullRefund,
            items: items,
        };
        const created = await refundsApi('/api/refunds', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        msg.textContent =
            created.status === 'approved'
                ? `Refund ${created.refund_number} approved (${formatMoney(created.amount)}).`
                : `Refund ${created.refund_number} submitted — pending supervisor approval.`;
        msg.style.color = '#22c55e';
        document.getElementById('refund-reason').value = '';
        document.getElementById('refund-notes').value = '';
        document.getElementById('refund-full').checked = false;
        saleSummary = null;
        document.getElementById('sale-preview').style.display = 'none';
        document.getElementById('sale-items-wrap').style.display = 'none';
        await loadRefunds();
    } catch (e) {
        msg.textContent = e.message || 'Could not submit refund.';
        msg.style.color = '#ef4444';
    } finally {
        submitBtn.disabled = !saleSummary;
    }
}

async function approveRefund(id) {
    if (!confirm('Approve this refund? Stock will be restored and accounts updated.')) return;
    try {
        await refundsApi('/api/refunds/' + id + '/approve', { method: 'POST', body: '{}' });
        await loadRefunds();
    } catch (e) {
        alert(e.message || 'Approve failed');
    }
}

async function rejectRefund(id) {
    const reason = prompt('Rejection reason (optional):');
    if (reason === null) return;
    try {
        await refundsApi('/api/refunds/' + id + '/reject', {
            method: 'POST',
            body: JSON.stringify({ rejection_reason: reason || null }),
        });
        await loadRefunds();
    } catch (e) {
        alert(e.message || 'Reject failed');
    }
}

document.addEventListener('DOMContentLoaded', async function () {
    const ok = await ensureAuthenticated();
    if (!ok) return;

    document.getElementById('btn-load-sale')?.addEventListener('click', loadSaleForRefund);
    document.getElementById('btn-submit-refund')?.addEventListener('click', submitRefund);
    document.getElementById('btn-refresh-refunds')?.addEventListener('click', loadRefunds);
    document.getElementById('filter-status')?.addEventListener('change', filterAndRenderRefunds);
    document.getElementById('refund-search')?.addEventListener('input', filterAndRenderRefunds);
    document.getElementById('refund-full')?.addEventListener('change', function () {
        const disabled = this.checked;
        document.querySelectorAll('.refund-qty-input').forEach((inp) => {
            inp.disabled = disabled;
            if (disabled) inp.value = '0';
        });
    });

    document.getElementById('refunds-body')?.addEventListener('click', function (e) {
        const approve = e.target.getAttribute('data-approve');
        const reject = e.target.getAttribute('data-reject');
        if (approve) approveRefund(Number(approve));
        if (reject) rejectRefund(Number(reject));
    });

    document.getElementById('btn-back-pos')?.addEventListener('click', () => {
        window.location.href = '/';
    });
    document.getElementById('btn-refunds-logout')?.addEventListener('click', () => {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.href = '/';
    });

    await loadRefunds();
});

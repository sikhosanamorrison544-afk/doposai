/**
 * Stock Transfers (Section 15) — page module for /stock-transfers.
 *
 * Wires the exact /api/transfers backend contract:
 *   list / get / create / PATCH draft / items / request / approve / reject /
 *   cancel / dispatch / receive.
 *
 * Item entry uses the existing /api/products search scoped to the chosen
 * source branch via the X-Branch-Id header. On-hand / reserved / available
 * quantities are branch-authoritative (BranchProductStock) — never the
 * consolidated Product.stock_qty shadow. There is no
 * /api/transfers/availability route in the backend.
 *
 * Auth: Bearer token from localStorage 'pos_token' (never cookies only).
 * Permission gating is a usability layer; the backend stays authoritative.
 */
(function (global) {
  'use strict';

  // ---------- state ----------
  let token = null;
  let user = null;
  let userPermissions = [];
  let branches = [];
  let transfers = [];
  let currentTransfer = null;   // loaded detail transfer
  let currentPage = 0;          // 0-based
  let pageSize = 20;
  let totalRows = 0;
  let filters = { status: '', from: '', to: '', q: '' };
  let createItems = [];         // [{product_id, product_name, barcode, quantity, on_hand, reserved, available}]
  let productOptions = [];
  let createClientTransferId = null;
  let editTransferId = null;    // non-null when the create modal edits a draft
  let editOriginalItemIds = []; // backend item ids present when the draft was opened for editing
  let busy = false;             // global double-submit guard
  let pendingConfirm = null;    // {kind, transferId, payload}

  const PERMS = {
    VIEW: 'branch.transfer.view',
    CREATE: 'branch.transfer.create',
    REQUEST: 'branch.transfer.request',
    APPROVE: 'branch.transfer.approve',
    REJECT: 'branch.transfer.reject',
    CANCEL: 'branch.transfer.cancel',
    DISPATCH: 'branch.transfer.dispatch',
    RECEIVE: 'branch.transfer.receive',
  };

  // Derived from the backend service (enterprise_models) — never invented.
  const STATUS_LABELS = {
    draft: 'Draft',
    requested: 'Requested',
    approved: 'Approved',
    dispatched: 'Dispatched',
    in_transit: 'In transit',
    received: 'Received',
    rejected: 'Rejected',
    cancelled: 'Cancelled',
  };
  // ---------- helpers ----------

  function $(id) {
    return document.getElementById(id);
  }

  function esc(v) {
    if (v === null || v === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(v);
    return div.innerHTML;
  }

  function fmtQty(v) {
    const n = Number(v);
    if (!isFinite(n)) return '0';
    return String(n);
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      return d.toLocaleString();
    } catch (_) {
      return String(iso);
    }
  }

  function statusLabel(s) {
    return STATUS_LABELS[s] || (s ? String(s) : '—');
  }

  function statusClass(s) {
    const safe = String(s || '').replace(/[^a-z0-9_]/gi, '_');
    return 'badge badge-' + (safe || 'draft');
  }

  function branchName(id) {
    for (let i = 0; i < branches.length; i++) {
      if (Number(branches[i].id) === Number(id)) {
        return (branches[i].name || branches[i].code || 'Branch ' + id);
      }
    }
    return 'Branch #' + id;
  }

  function hasPerm(name) {
    return Array.isArray(userPermissions) && userPermissions.indexOf(name) !== -1;
  }

  function uuid() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      try { return crypto.randomUUID(); } catch (_) { /* fall through */ }
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function toast(msg, type) {
    const wrap = $('toast-wrap');
    if (!wrap) return;
    const el = document.createElement('div');
    el.className = 'toast toast-' + (type || 'info');
    el.textContent = msg;
    wrap.appendChild(el);
    setTimeout(function () {
      el.remove();
    }, 5000);
  }

  function sumQty(items, key) {
    if (!Array.isArray(items)) return 0;
    return items.reduce(function (acc, it) {
      return acc + (Number(it[key]) || 0);
    }, 0);
  }

  // ---------- auth / api ----------

  async function ensureAuthenticated() {
    const savedToken = localStorage.getItem('pos_token');
    if (!savedToken) {
      window.location.replace('/');
      return false;
    }
    token = savedToken.trim();
    try {
      const savedUser = localStorage.getItem('pos_user');
      user = savedUser ? JSON.parse(savedUser) : null;
    } catch (_) {
      user = null;
    }
    const infoEl = $('xfer-user-info');
    if (infoEl && user) {
      infoEl.textContent = user.username + (user.role ? ' (' + user.role + ')' : '');
    }
    try {
      const me = await transfersApi('/api/auth/me', { _raw: true });
      userPermissions = (me && me.permissions) || [];
      if (infoEl && me) {
        infoEl.textContent = me.username + (me.role ? ' (' + me.role + ')' : '');
      }
    } catch (e) {
      userPermissions = [];
    }
    return true;
  }

  function activeBranchHeader() {
    try {
      const ctx = JSON.parse(localStorage.getItem('pos_branch_ctx') || 'null');
      if (ctx && ctx.branchId && ctx.scope !== 'all') {
        return String(ctx.branchId);
      }
    } catch (_) {}
    return null;
  }

  async function transfersApi(path, options) {
    options = options || {};
    if (!token && !options._raw) {
      const ok = await ensureAuthenticated();
      if (!ok) throw new Error('Not authenticated');
    }
    const headers = Object.assign({}, options.headers || {}, {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + token,
    });
    const branchId = activeBranchHeader();
    if (branchId && !(headers['X-Branch-Id'])) {
      headers['X-Branch-Id'] = branchId;
    }
    const res = await fetch(path, Object.assign({}, options, { headers }));
    if (!res.ok) {
      let msg = res.statusText || 'Request failed';
      try {
        const j = await res.json();
        if (j && j.detail !== undefined) {
          if (typeof j.detail === 'string') {
            msg = j.detail;
          } else if (Array.isArray(j.detail) && j.detail.length) {
            // FastAPI 422 validation errors: [{loc, msg, type}, ...]
            const first = j.detail[0];
            msg = (first && first.msg) ? first.msg : JSON.stringify(j.detail);
          } else {
            msg = JSON.stringify(j.detail);
          }
        } else if (j && j.message) {
          msg = j.message;
        }
      } catch (_) { /* non-JSON body */ }
      const err = new Error(msg);
      err.status = res.status;
      if (res.status === 401) {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.replace('/');
      }
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function showFormError(elId, err) {
    const el = $(elId);
    if (!el) return;
    let msg = (err && err.message) ? err.message : 'Something went wrong. Please try again.';
    if (err && err.status === 403) msg = permissionMessage();
    if (err && err.status === 500) msg = 'Server error. Please try again or contact support.';
    el.textContent = msg;
    el.style.display = 'block';
  }

  function permissionMessage() {
    return 'You do not have permission to perform this action on stock transfers.';
  }

  // ---------- branches ----------

  async function loadBranches() {
    try {
      branches = await transfersApi('/api/branches');
      if (!Array.isArray(branches)) branches = [];
    } catch (e) {
      branches = [];
    }
    const fromSel = $('filter-from');
    const toSel = $('filter-to');
    const createFrom = $('create-from');
    const createTo = $('create-to');
    const opts = branches.map(function (b) {
      return '<option value="' + Number(b.id) + '">' + esc(b.name || b.code || 'Branch ' + b.id) + '</option>';
    }).join('');
    [fromSel, toSel].forEach(function (sel) {
      if (sel) {
        const cur = sel.value;
        sel.innerHTML = '<option value="">All ' + (sel === fromSel ? 'sources' : 'destinations') + '</option>' + opts;
        if (cur) sel.value = cur;
      }
    });
    if (createFrom && createTo) {
      createFrom.innerHTML = opts;
      createTo.innerHTML = opts;
    }
    const ctx = readBranchCtx();
    if (createFrom && ctx && ctx.branchId && ctx.scope !== 'all') {
      createFrom.value = String(ctx.branchId);
    }
  }

  function readBranchCtx() {
    try {
      return JSON.parse(localStorage.getItem('pos_branch_ctx') || 'null');
    } catch (_) {
      return null;
    }
  }

  // ---------- list ----------

  async function loadTransfers() {
    const loading = $('transfers-loading');
    const errBox = $('transfers-error');
    const table = $('transfers-table');
    const mobile = $('transfers-mobile');
    const empty = $('transfers-empty');
    if (loading) loading.style.display = 'block';
    if (errBox) errBox.style.display = 'none';
    if (table) table.style.display = 'none';
    if (mobile) mobile.style.display = 'none';
    if (empty) empty.style.display = 'none';
    const params = [];
    if (filters.status) params.push('status=' + encodeURIComponent(filters.status));
    if (filters.from) params.push('from_branch_id=' + encodeURIComponent(filters.from));
    if (filters.to) params.push('to_branch_id=' + encodeURIComponent(filters.to));
    params.push('limit=' + pageSize);
    params.push('offset=' + (currentPage * pageSize));
    const url = '/api/transfers?' + params.join('&');
    try {
      const rows = await transfersApi(url);
      transfers = Array.isArray(rows) ? rows : [];
      totalRows = transfers.length < pageSize && currentPage === 0 ? transfers.length : -1;
      if (loading) loading.style.display = 'none';
      renderList();
    } catch (e) {
      if (loading) loading.style.display = 'none';
      if (errBox) {
        let msg = (e && e.message) ? e.message : 'Could not load transfers.';
        if (e && e.status === 403) msg = permissionMessage();
        if (e && e.status === 500) msg = 'Server error. Please try again or contact support.';
        errBox.textContent = '⚠ ' + msg;
        errBox.style.display = 'block';
      }
    }
  }

  function renderList() {
    const q = (filters.q || '').trim().toLowerCase();
    const visible = q
      ? transfers.filter(function (t) {
          return (
            String(t.transfer_number || '').toLowerCase().indexOf(q) !== -1 ||
            String(t.id).toLowerCase().indexOf(q) !== -1 ||
            String(t.notes || '').toLowerCase().indexOf(q) !== -1
          );
        })
      : transfers;
    const table = $('transfers-table');
    const mobile = $('transfers-mobile');
    const empty = $('transfers-empty');
    const countEl = $('xfer-count');
    if (countEl) {
      countEl.textContent = visible.length ? visible.length + ' transfer(s)' : '';
    }
    if (!visible.length) {
      if (table) table.style.display = 'none';
      if (mobile) mobile.style.display = 'none';
      if (empty) {
        empty.textContent = q
          ? 'No transfers match the current search.'
          : 'No transfers match these filters yet. Use “New Stock Transfer” to create a draft.';
        empty.style.display = 'block';
      }
      renderPagination(0);
      return;
    }
    if (empty) empty.style.display = 'none';
    if (table) table.style.display = 'block';
    if (mobile) mobile.style.display = 'block';
    const body = $('transfers-body');
    if (body) {
      body.innerHTML = visible.map(renderDesktopRow).join('');
    }
    if (mobile) {
      mobile.innerHTML = visible.map(renderMobileCard).join('');
    }
    renderPagination(visible.length);
  }

  function actionButtons(t) {
    const st = t.status;
    const btns = [];
    btns.push({ label: 'View', kind: 'view', cls: 'primary small', always: true });
    if (st === 'draft') {
      if (hasPerm(PERMS.CREATE)) btns.push({ label: 'Edit', kind: 'edit', cls: 'small' });
      if (hasPerm(PERMS.REQUEST) && t.items && t.items.length > 0) {
        btns.push({ label: 'Request', kind: 'request', cls: 'small' });
      }
      if (hasPerm(PERMS.CANCEL)) btns.push({ label: 'Cancel', kind: 'cancel', cls: 'small' });
      if (hasPerm(PERMS.CREATE)) btns.push({ label: 'Delete', kind: 'delete', cls: 'danger-btn small' });
    } else if (st === 'requested') {
      if (hasPerm(PERMS.APPROVE)) btns.push({ label: 'Approve', kind: 'approve', cls: 'small' });
      if (hasPerm(PERMS.REJECT)) btns.push({ label: 'Reject', kind: 'reject', cls: 'danger-btn small' });
      if (hasPerm(PERMS.CANCEL)) btns.push({ label: 'Cancel', kind: 'cancel', cls: 'small' });
    } else if (st === 'approved') {
      if (hasPerm(PERMS.DISPATCH)) btns.push({ label: 'Dispatch', kind: 'dispatch', cls: 'small' });
      if (hasPerm(PERMS.CANCEL) && !hasDispatchedQty(t)) {
        btns.push({ label: 'Cancel', kind: 'cancel', cls: 'small' });
      }
    } else if (st === 'dispatched' || st === 'in_transit') {
      if (hasPerm(PERMS.RECEIVE)) btns.push({ label: 'Receive', kind: 'receive', cls: 'small' });
    }
    return btns;
  }

  function hasDispatchedQty(t) {
    if (!t.items) return false;
    return t.items.some(function (it) {
      return Number(it.quantity_dispatched) > 0;
    });
  }

  function renderDesktopRow(t) {
    const btns = actionButtons(t).map(function (b) {
      return '<button type="button" class="' + b.cls + '" data-action="' + b.kind + '" data-id="' + Number(t.id) + '">' + b.label + '</button>';
    }).join(' ');
    return (
      '<tr>' +
      '<td>' + esc(t.transfer_number || '#' + t.id) + '</td>' +
      '<td>' + esc(branchName(t.from_branch_id)) + '</td>' +
      '<td>' + esc(branchName(t.to_branch_id)) + '</td>' +
      '<td><span class="' + statusClass(t.status) + '">' + esc(statusLabel(t.status)) + '</span></td>' +
      '<td>' + fmtQty(sumQty(t.items, 'quantity_requested')) + '</td>' +
      '<td>' + fmtQty(sumQty(t.items, 'quantity_approved')) + '</td>' +
      '<td>' + fmtQty(sumQty(t.items, 'quantity_dispatched')) + '</td>' +
      '<td>' + fmtQty(sumQty(t.items, 'quantity_received')) + '</td>' +
      '<td>' + esc(t.created_by_name || ('User #' + t.created_by)) + '</td>' +
      '<td>' + esc(fmtDate(t.created_at)) + '</td>' +
      '<td>' + esc(fmtDate(t.updated_at || t.created_at)) + '</td>' +
      '<td class="xfer-actions">' + btns + '</td>' +
      '</tr>'
    );
  }

  function renderMobileCard(t) {
    const btns = actionButtons(t).map(function (b) {
      return '<button type="button" class="' + b.cls + '" data-action="' + b.kind + '" data-id="' + Number(t.id) + '">' + b.label + '</button>';
    }).join(' ');
    return (
      '<div class="card" role="listitem">' +
      '<div class="row"><b>' + esc(t.transfer_number || '#' + t.id) + '</b><span class="' + statusClass(t.status) + '">' + esc(statusLabel(t.status)) + '</span></div>' +
      '<div class="row"><span>Source</span><span>' + esc(branchName(t.from_branch_id)) + '</span></div>' +
      '<div class="row"><span>Destination</span><span>' + esc(branchName(t.to_branch_id)) + '</span></div>' +
      '<div class="row"><span>Requested / Approved</span><span>' + fmtQty(sumQty(t.items, 'quantity_requested')) + ' / ' + fmtQty(sumQty(t.items, 'quantity_approved')) + '</span></div>' +
      '<div class="row"><span>Dispatched / Received</span><span>' + fmtQty(sumQty(t.items, 'quantity_dispatched')) + ' / ' + fmtQty(sumQty(t.items, 'quantity_received')) + '</span></div>' +
      '<div class="row"><span>Created</span><span>' + esc(fmtDate(t.created_at)) + '</span></div>' +
      '<div class="xfer-actions" style="margin-top:8px;">' + btns + '</div>' +
      '</div>'
    );
  }

  function renderPagination(pageLen) {
    const pag = $('pagination');
    if (!pag) return;
    const hasPrev = currentPage > 0;
    const hasNext = pageLen >= pageSize;
    if (!hasPrev && !hasNext) {
      pag.style.display = 'none';
      return;
    }
    pag.style.display = 'flex';
    const info = $('page-info');
    if (info) {
      info.textContent = 'Page ' + (currentPage + 1) + (totalRows >= 0 ? ' · ' + totalRows + ' total' : '');
    }
    const prev = $('btn-page-prev');
    const next = $('btn-page-next');
    if (prev) prev.disabled = !hasPrev;
    if (next) next.disabled = !hasNext;
  }

  // ---------- details ----------

  async function openDetail(id) {
    try {
      const t = await transfersApi('/api/transfers/' + encodeURIComponent(id));
      currentTransfer = t;
      renderDetail(t);
      const modal = $('detail-modal');
      if (modal) modal.classList.add('show');
    } catch (e) {
      if (e && e.status === 404) {
        toast('Transfer not found.', 'error');
      } else {
        toast((e && e.message) || 'Could not load transfer.', 'error');
      }
    }
  }

  function closeDetail() {
    const modal = $('detail-modal');
    if (modal) modal.classList.remove('show');
    currentTransfer = null;
  }

  async function reloadDetail() {
    if (!currentTransfer) return;
    try {
      const t = await transfersApi('/api/transfers/' + encodeURIComponent(currentTransfer.id));
      currentTransfer = t;
      renderDetail(t);
    } catch (e) {
      toast((e && e.message) || 'Could not refresh transfer.', 'error');
    }
  }

  function actorCell(label, id, name) {
    if (!id) return null;
    return '<div class="kv-item"><div class="k">' + esc(label) + '</div><div class="v">' + esc(name || ('User #' + id)) + '</div></div>';
  }

  function renderDetail(t) {
    const title = $('detail-title');
    if (title) {
      title.textContent = (t.transfer_number || ('Transfer #' + t.id)) + ' — ' + statusLabel(t.status);
    }
    const body = $('detail-body');
    if (!body) return;
    const kvItems = [
      ['Source branch', branchName(t.from_branch_id)],
      ['Destination branch', branchName(t.to_branch_id)],
      ['Status', statusLabel(t.status)],
      ['Version', String(t.version != null ? t.version : '—')],
      ['Created', fmtDate(t.created_at)],
      ['Last updated', fmtDate(t.updated_at || t.created_at)],
    ];
    const actors = [
      actorCell('Created by', t.created_by, t.created_by_name),
      actorCell('Requested by', t.requested_by_id, t.requested_by_name),
      actorCell('Approved by', t.approved_by_id, t.approved_by_name),
      actorCell('Dispatched by', t.dispatched_by_id, t.dispatched_by_name),
      actorCell('Received by', t.received_by, t.received_by_name),
      actorCell('Rejected by', t.rejected_by_id, t.rejected_by_name),
      actorCell('Cancelled by', t.cancelled_by_id, t.cancelled_by_name),
    ].filter(Boolean).join('');
    const times = [
      ['Requested at', fmtDate(t.requested_at)],
      ['Approved at', fmtDate(t.approved_at)],
      ['Dispatched at', fmtDate(t.dispatched_at)],
      ['Received at', fmtDate(t.received_at)],
      ['Rejected at', fmtDate(t.rejected_at)],
      ['Cancelled at', fmtDate(t.cancelled_at)],
    ].map(function (row) {
      return '<div class="kv-item"><div class="k">' + row[0] + '</div><div class="v">' + row[1] + '</div></div>';
    }).join('');
    const notes = [
      ['Notes', t.notes],
      ['Request notes', t.request_notes],
      ['Approval notes', t.approval_notes],
      ['Dispatch notes', t.dispatch_notes],
      ['Receipt notes', t.receipt_notes],
      ['Rejection reason', t.rejection_reason],
      ['Cancellation reason', t.cancellation_reason],
    ].filter(function (row) { return row[1]; }).map(function (row) {
      return '<div class="notes-block"><b>' + esc(row[0]) + ':</b> ' + esc(row[1]) + '</div>';
    }).join('') || '<p class="muted" style="font-size:13px;">No notes.</p>';

    const itemRows = (t.items || []).map(function (it) {
      return (
        '<tr>' +
        '<td>' + esc(it.product_name || ('Product #' + it.product_id)) + '</td>' +
        '<td>' + fmtQty(it.quantity_requested) + '</td>' +
        '<td>' + fmtQty(it.quantity_approved) + '</td>' +
        '<td>' + fmtQty(it.quantity_dispatched) + '</td>' +
        '<td>' + fmtQty(it.quantity_received) + '</td>' +
        '<td>' + fmtQty(it.quantity_damaged) + '</td>' +
        '<td>' + fmtQty(it.quantity_missing) + '</td>' +
        '<td>' + (it.unit_cost_snapshot != null ? fmtQty(it.unit_cost_snapshot) : '—') + '</td>' +
        '</tr>'
      );
    }).join('');

    const btns = actionButtons(t).map(function (b) {
      return '<button type="button" class="' + b.cls + '" data-detail-action="' + b.kind + '" data-id="' + Number(t.id) + '">' + b.label + '</button>';
    }).join(' ');

    body.innerHTML =
      '<div class="kv">' + kvItems.map(function (row) {
        return '<div class="kv-item"><div class="k">' + esc(row[0]) + '</div><div class="v">' + esc(row[1]) + '</div></div>';
      }).join('') + '</div>' +
      '<h3 style="margin:14px 0 6px;font-size:14px;">Actors</h3>' +
      '<div class="kv">' + (actors || '<p class="muted" style="font-size:13px;">No actors yet.</p>') + '</div>' +
      '<h3 style="margin:14px 0 6px;font-size:14px;">Timestamps</h3>' +
      '<div class="kv">' + times + '</div>' +
      '<h3 style="margin:14px 0 6px;font-size:14px;">Notes</h3>' + notes +
      '<h3 style="margin:14px 0 6px;font-size:14px;">Items</h3>' +
      '<div style="overflow-x:auto;"><table class="xfer-table" style="min-width:620px;"><thead><tr>' +
      '<th>Product</th><th>Requested</th><th>Approved</th><th>Dispatched</th><th>Received</th><th>Damaged</th><th>Missing</th><th>Unit cost</th>' +
      '</tr></thead><tbody>' + itemRows + '</tbody></table></div>' +
      '<div class="xfer-actions" style="margin-top:14px;">' + btns + '</div>';
  }

  // ---------- confirm modal ----------

  function showConfirm(title, message, formHtml, onOk) {
    const modal = $('confirm-modal');
    if (!modal) return;
    $('confirm-title').textContent = title || 'Confirm';
    $('confirm-message').textContent = message || '';
    const formBox = $('confirm-form');
    formBox.innerHTML = formHtml || '';
    const msgBox = $('confirm-message-box');
    msgBox.textContent = '';
    msgBox.style.display = 'none';
    modal.classList.add('show');
    const okBtn = $('confirm-ok');
    okBtn.textContent = title || 'Confirm';
    okBtn.disabled = false;
    okBtn.onclick = async function () {
      okBtn.disabled = true;
      try {
        await onOk();
      } catch (e) {
        okBtn.disabled = false;
        msgBox.textContent = (e && e.message) ? e.message : 'Action failed.';
        msgBox.style.display = 'block';
        if (e && e.status === 409) {
          msgBox.textContent += ' The transfer may have changed. Please close and reopen it to refresh.';
        }
        if (e && e.status === 401) return;
      }
    };
  }

  function closeConfirm() {
    const modal = $('confirm-modal');
    if (modal) modal.classList.remove('show');
    pendingConfirm = null;
  }

  // ---------- lifecycle ----------

  function transferById(id) {
    for (let i = 0; i < transfers.length; i++) {
      if (Number(transfers[i].id) === Number(id)) return transfers[i];
    }
    return null;
  }

  function handleAction(kind, id) {
    if (kind === 'view') { openDetail(id); return; }
    if (kind === 'edit') { openCreateForEdit(id); return; }
    if (kind === 'request') { confirmRequest(id); return; }
    if (kind === 'approve') { confirmApprove(id); return; }
    if (kind === 'reject') { confirmReject(id); return; }
    if (kind === 'cancel') { confirmCancel(id); return; }
    if (kind === 'delete') { confirmDelete(id); return; }
    if (kind === 'dispatch') { confirmDispatch(id); return; }
    if (kind === 'receive') { openReceive(id); return; }
    toast('Unknown action.', 'error');
  }

  function confirmRequest(id) {
    const t = transferById(id) || currentTransfer;
    showConfirm('Request approval', 'Request approval for ' + (t ? t.transfer_number : '#' + id) + '? The transfer moves from draft to requested.', '',
      async function () {
        const updated = await transfersApi('/api/transfers/' + encodeURIComponent(id) + '/request', {
          method: 'POST',
          body: JSON.stringify({ notes: null }),
        });
        closeConfirm();
        afterMutation(updated);
      });
  }

  function confirmApprove(id) {
    const t = transferById(id) || currentTransfer;
    const totalReq = fmtQty(sumQty(t && t.items, 'quantity_requested'));
    showConfirm('Approve transfer', 'Approve ' + (t ? t.transfer_number : '#' + id) + '? Approving RESERVES the requested quantity (' + totalReq + ' units) at the source branch — stock does not move until dispatch.', '',
      async function () {
        const updated = await transfersApi('/api/transfers/' + encodeURIComponent(id) + '/approve', {
          method: 'POST',
          body: JSON.stringify({ notes: null }),
        });
        closeConfirm();
        afterMutation(updated);
      });
  }

  function confirmReject(id) {
    showConfirm('Reject transfer', 'Rejecting returns the transfer to a terminal rejected state. A rejection reason is required.',
      '<label for="reject-reason" style="display:block;font-size:12px;opacity:0.85;margin-bottom:4px;">Rejection reason</label>' +
      '<textarea id="reject-reason" maxlength="500" placeholder="Why is this transfer rejected?" style="min-height:64px;resize:vertical;"></textarea>',
      async function () {
        const reasonInput = $('reject-reason');
        const reason = (reasonInput && reasonInput.value || '').trim();
        if (!reason) {
          throw new Error('A rejection reason is required.');
        }
        const updated = await transfersApi('/api/transfers/' + encodeURIComponent(id) + '/reject', {
          method: 'POST',
          body: JSON.stringify({ reason: reason }),
        });
        closeConfirm();
        afterMutation(updated);
      });
  }

  function confirmCancel(id) {
    const t = transferById(id) || currentTransfer;
    const isApproved = t && t.status === 'approved';
    const msg = isApproved
      ? 'Cancel this transfer? Approval reservations at the source branch will be released. This cannot be cancelled once anything is dispatched.'
      : 'Cancel this transfer? Draft/requested transfers can be cancelled without affecting stock.';
    showConfirm('Cancel transfer', msg, '',
      async function () {
        const updated = await transfersApi('/api/transfers/' + encodeURIComponent(id) + '/cancel', {
          method: 'POST',
          body: JSON.stringify({ reason: null }),
        });
        closeConfirm();
        afterMutation(updated);
      });
  }

  function confirmDelete(id) {
    showConfirm('Delete draft', 'Delete this draft transfer and all its items? This cannot be undone.', '',
      async function () {
        await transfersApi('/api/transfers/' + encodeURIComponent(id), { method: 'DELETE' });
        closeConfirm();
        toast('Draft deleted.', 'success');
        await loadTransfers();
      });
  }

  function confirmDispatch(id) {
    const t = transferById(id) || currentTransfer;
    const approved = fmtQty(sumQty(t && t.items, 'quantity_approved'));
    showConfirm('Dispatch stock', 'Dispatch ' + (t ? t.transfer_number : '#' + id) + '? This reduces the SOURCE branch physical (on-hand) stock by ' + approved + ' units and moves it into transit.', '',
      async function () {
        const updated = await transfersApi('/api/transfers/' + encodeURIComponent(id) + '/dispatch', {
          method: 'POST',
          body: JSON.stringify({ notes: null }),
        });
        closeConfirm();
        afterMutation(updated);
      });
  }


  function afterMutation(updated) {
    toast(updated && updated.transfer_number
      ? (updated.transfer_number + ' is now ' + statusLabel(updated.status) + '.')
      : 'Transfer updated.', 'success');
    if (currentTransfer && updated && Number(currentTransfer.id) === Number(updated.id)) {
      currentTransfer = updated;
    }
    // Refresh the list; also refresh branch stock numbers after dispatch/receive.
    loadTransfers();
    if (currentTransfer && updated && Number(currentTransfer.id) === Number(updated.id)) {
      renderDetail(updated);
    }
  }

  // ---------- receive ----------

  let receiveClientMovementId = null;

  function remainingReceive(it) {
    const dispatched = Number(it.quantity_dispatched) || 0;
    const accounted = (Number(it.quantity_received) || 0) + (Number(it.quantity_damaged) || 0) + (Number(it.quantity_missing) || 0);
    return Math.max(0, dispatched - accounted);
  }

  function openReceive(id) {
    const t = transferById(id) || currentTransfer;
    if (!t) return;
    if (busy) return;
    receiveClientMovementId = 'recv-' + uuid();
    const items = t.items || [];
    const rows = items.map(function (it) {
      const remaining = remainingReceive(it);
      return (
        '<div class="receive-item" data-item-id="' + Number(it.id) + '">' +
        '<div style="font-weight:600;font-size:13px;">' + esc(it.product_name || ('Product #' + it.product_id)) + '</div>' +
        '<div class="muted" style="font-size:12px;margin:4px 0;">Dispatched: ' + fmtQty(it.quantity_dispatched) +
        ' · Received: ' + fmtQty(it.quantity_received) +
        ' · Damaged: ' + fmtQty(it.quantity_damaged) +
        ' · Missing: ' + fmtQty(it.quantity_missing) +
        ' · Remaining: ' + fmtQty(remaining) + '</div>' +
        '<div class="qty-grid">' +
        '<div><label>Accepted</label><input type="number" class="rcv-accepted" min="0" step="any" value="0" data-max="' + remaining + '"></div>' +
        '<div><label>Damaged</label><input type="number" class="rcv-damaged" min="0" step="any" value="0" data-max="' + remaining + '"></div>' +
        '<div><label>Missing</label><input type="number" class="rcv-missing" min="0" step="any" value="0" data-max="' + remaining + '"></div>' +
        '</div>' +
        '</div>'
      );
    }).join('');
    showConfirm('Receive stock', 'Only the ACCEPTED quantity enters the destination branch available stock. Damaged and missing quantities complete the transfer without adding destination stock.',
      '<div style="max-height:40vh;overflow-y:auto;padding-right:4px;">' + rows + '</div>' +
      '<div style="margin-top:10px;"><label style="display:block;font-size:12px;opacity:0.85;margin-bottom:4px;">Receipt notes (optional)</label>' +
      '<input type="text" id="rcv-notes" maxlength="500" autocomplete="off"></div>',
      submitReceive);
  }

  async function submitReceive() {
    const t = currentTransfer;
    if (!t) {
      throw new Error('Transfer not loaded. Please open the transfer and try again.');
    }
    const items = t.items || [];
    const lines = [];
    const rows = document.querySelectorAll('#confirm-form .receive-item');
    rows.forEach(function (rowEl) {
      const itemId = Number(rowEl.getAttribute('data-item-id'));
      const accepted = Number(rowEl.querySelector('.rcv-accepted').value) || 0;
      const damaged = Number(rowEl.querySelector('.rcv-damaged').value) || 0;
      const missing = Number(rowEl.querySelector('.rcv-missing').value) || 0;
      const max = Number(rowEl.querySelector('.rcv-accepted').getAttribute('data-max')) || 0;
      if (accepted < 0 || damaged < 0 || missing < 0) {
        throw new Error('Receipt quantities cannot be negative.');
      }
      if (accepted + damaged + missing > max) {
        throw new Error('Accepted + damaged + missing cannot exceed the remaining dispatched quantity (' + fmtQty(max) + ').');
      }
      if (accepted + damaged + missing > 0) {
        lines.push({ item_id: itemId, accepted: accepted, damaged: damaged, missing: missing });
      }
    });
    if (!lines.length) {
      throw new Error('Enter at least one received quantity to continue.');
    }
    const notesInput = $('rcv-notes');
    const body = {
      lines: lines,
      notes: notesInput ? notesInput.value : null,
      client_movement_id: receiveClientMovementId,
    };
    const updated = await transfersApi('/api/transfers/' + encodeURIComponent(t.id) + '/receive', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    closeConfirm();
    afterMutation(updated);
  }
  // ---------- create / edit draft ----------

  function openCreate() {
    editTransferId = null;
    editOriginalItemIds = [];
    createItems = [];
    productOptions = [];
    createClientTransferId = 'xfer-' + uuid();
    const modal = $('create-modal');
    if (!modal) return;
    const title = modal.querySelector('h2');
    if (title) title.textContent = 'New Stock Transfer';
    const saveBtn = $('btn-create-save');
    if (saveBtn) saveBtn.textContent = 'Create draft';
    $('create-notes').value = '';
    $('create-product-q').value = '';
    $('product-options').innerHTML = '';
    $('create-item-rows').innerHTML = '';
    $('create-message').style.display = 'none';
    $('create-message').textContent = '';
    const ctx = readBranchCtx();
    if (ctx && ctx.branchId && ctx.scope !== 'all') {
      $('create-from').value = String(ctx.branchId);
    }
    const dst = $('create-to');
    if (dst && $('create-from').value) {
      const others = branches.filter(function (b) { return String(b.id) !== $('create-from').value; });
      if (others.length) dst.value = String(others[0].id);
    }
    modal.classList.add('show');
    $('create-product-q').focus();
  }

  async function openCreateForEdit(id) {
    try {
      const t = await transfersApi('/api/transfers/' + encodeURIComponent(id));
      if (t.status !== 'draft') {
        toast('Only draft transfers can be edited.', 'error');
        return;
      }
      editTransferId = t.id;
      createClientTransferId = t.client_transfer_id || ('xfer-' + uuid());
      editOriginalItemIds = (t.items || []).map(function (it) { return it.id; });
      createItems = (t.items || []).map(function (it) {
        return {
          item_id: it.id,
          product_id: it.product_id,
          product_name: it.product_name,
          barcode: null,
          quantity: Number(it.quantity_requested) || 0,
          on_hand: null,
          reserved: null,
          available: null,
        };
      });
      productOptions = [];
      const modal = $('create-modal');
      if (!modal) return;
      const title = modal.querySelector('h2');
      if (title) title.textContent = 'Edit Draft ' + t.transfer_number;
      const saveBtn = $('btn-create-save');
      if (saveBtn) saveBtn.textContent = 'Save changes';
      $('create-notes').value = t.notes || '';
      $('create-product-q').value = '';
      $('product-options').innerHTML = '';
      $('create-message').style.display = 'none';
      $('create-message').textContent = '';
      $('create-from').value = String(t.from_branch_id);
      $('create-to').value = String(t.to_branch_id);
      $('create-from').disabled = true;
      $('create-to').disabled = true;
      renderCreateItems();
      modal.classList.add('show');
      $('create-product-q').focus();
    } catch (e) {
      toast((e && e.message) || 'Could not load draft for editing.', 'error');
    }
  }

  function closeCreate() {
    const modal = $('create-modal');
    if (modal) modal.classList.remove('show');
    $('create-from').disabled = false;
    $('create-to').disabled = false;
    editTransferId = null;
    editOriginalItemIds = [];
    createItems = [];
  }

  async function searchProducts() {
    const fromVal = $('create-from').value;
    if (!fromVal) {
      toast('Select a source branch first.', 'info');
      return;
    }
    const q = ($('create-product-q').value || '').trim();
    if (!q) {
      toast('Type a product name or barcode to search.', 'info');
      return;
    }
    const box = $('product-options');
    if (box) box.innerHTML = '<p class="muted" style="font-size:13px;">Searching…</p>';
    try {
      // Use the existing product search endpoint, scoped to the chosen source
      // branch via the X-Branch-Id header. stockQty/reservedQty/availableQty are
      // branch-authoritative (BranchProductStock), never the Product.stock_qty shadow.
      const rows = await transfersApi(
        '/api/products?q=' + encodeURIComponent(q) + '&limit=12&skip_total=1',
        { headers: { 'X-Branch-Id': fromVal } }
      );
      productOptions = Array.isArray(rows) ? rows : [];
      if (box) {
        if (!productOptions.length) {
          box.innerHTML = '<p class="muted" style="font-size:13px;">No products found.</p>';
          return;
        }
        box.innerHTML = productOptions.map(function (p) {
          const added = createItems.some(function (it) { return Number(it.product_id) === Number(p.id); });
          return (
            '<div style="display:flex;align-items:center;gap:8px;padding:6px 4px;border-bottom:1px solid rgba(255,255,255,0.08);font-size:13px;">' +
            '<span style="flex:1;">' + esc(p.name) + ' <span class="muted">' + (p.barcode ? esc(p.barcode) : '') + '</span></span>' +
            '<span class="stock-hint">On hand ' + fmtQty(p.stockQty) + ' · Reserved ' + fmtQty(p.reservedQty) + ' · Available ' + fmtQty(p.availableQty) + '</span>' +
            (added
              ? '<span class="muted" style="font-size:12px;">Already added</span>'
              : '<button type="button" class="small" data-add-product="' + Number(p.id) + '" data-name="' + esc(p.name) + '" data-barcode="' + esc(p.barcode || '') + '" data-onhand="' + p.stockQty + '" data-reserved="' + p.reservedQty + '" data-available="' + p.availableQty + '">Add</button>') +
            '</div>'
          );
        }).join('');
      }
    } catch (e) {
      if (box) box.innerHTML = '<p class="muted" style="font-size:13px;">Product search failed.</p>';
      toast((e && e.message) || 'Product search failed.', 'error');
    }
  }

  function addItemToCreate(productId, name, barcode, onHand, reserved, available) {
    if (createItems.some(function (it) { return Number(it.product_id) === Number(productId); })) {
      toast('That product is already on the transfer.', 'info');
      return;
    }
    createItems.push({
      item_id: null,
      product_id: Number(productId),
      product_name: name,
      barcode: barcode,
      quantity: 1,
      on_hand: onHand,
      reserved: reserved,
      available: available,
    });
    renderCreateItems();
  }

  function removeCreateItem(idx) {
    if (idx < 0 || idx >= createItems.length) return;
    createItems.splice(idx, 1);
    renderCreateItems();
  }

  function renderCreateItems() {
    const box = $('create-item-rows');
    if (!box) return;
    if (!createItems.length) {
      box.innerHTML = '<p class="muted" style="font-size:13px;">No items added yet. Search and add products above.</p>';
      return;
    }
    box.innerHTML = createItems.map(function (it, idx) {
      const stockHint = it.on_hand != null
        ? '<div class="stock-hint">On hand ' + fmtQty(it.on_hand) + ' · Reserved ' + fmtQty(it.reserved) + ' · Available ' + fmtQty(it.available) + '</div>'
        : '<div class="stock-hint muted">Stock shown after selecting the source branch.</div>';
      return (
        '<div class="item-line" data-idx="' + idx + '">' +
        '<div>' + esc(it.product_name) + (it.barcode ? ' <span class="muted">(' + esc(it.barcode) + ')</span>' : '') + stockHint + '</div>' +
        '<input type="number" class="create-item-qty" min="0.0001" step="any" value="' + it.quantity + '" aria-label="Quantity for ' + esc(it.product_name) + '">' +
        '<span class="muted" style="font-size:12px;">qty</span>' +
        '<button type="button" class="danger-btn small" data-remove-item="' + idx + '">Remove</button>' +
        '</div>'
      );
    }).join('');
  }

  function collectCreateItems() {
    const items = [];
    const seen = {};
    document.querySelectorAll('#create-item-rows .item-line').forEach(function (rowEl) {
      const idx = Number(rowEl.getAttribute('data-idx'));
      const it = createItems[idx];
      if (!it) return;
      const qtyInput = rowEl.querySelector('.create-item-qty');
      const qty = Number(qtyInput.value);
      if (!isFinite(qty) || qty <= 0) {
        throw new Error('Quantity for "' + it.product_name + '" must be a positive number.');
      }
      if (seen[it.product_id]) {
        throw new Error('Product "' + it.product_name + '" appears more than once. Combine quantities into one line.');
      }
      seen[it.product_id] = true;
      items.push({ product_id: it.product_id, quantity: qty });
    });
    return items;
  }

  async function submitCreate() {
    if (busy) return;
    const msg = $('create-message');
    msg.style.display = 'none';
    msg.textContent = '';
    const fromVal = $('create-from').value;
    const toVal = $('create-to').value;
    if (!fromVal || !toVal) {
      msg.textContent = 'Select both a source and a destination branch.';
      msg.style.display = 'block';
      return;
    }
    if (fromVal === toVal) {
      msg.textContent = 'Source and destination branches must be different.';
      msg.style.display = 'block';
      return;
    }
    let items = [];
    try {
      items = collectCreateItems();
    } catch (e) {
      msg.textContent = e.message;
      msg.style.display = 'block';
      return;
    }
    busy = true;
    const saveBtn = $('btn-create-save');
    if (saveBtn) saveBtn.disabled = true;
    try {
      if (editTransferId != null) {
        const body = { notes: $('create-notes').value || null };
        const updated = await transfersApi('/api/transfers/' + encodeURIComponent(editTransferId), {
          method: 'PATCH',
          body: JSON.stringify(body),
        });
        // Apply item changes against the existing draft.
        const keptIds = [];
        for (const it of createItems) {
          const qty = Number(it.quantity);
          if (it.item_id != null) {
            keptIds.push(it.item_id);
            await transfersApi('/api/transfers/' + encodeURIComponent(editTransferId) + '/items/' + encodeURIComponent(it.item_id), {
              method: 'PUT',
              body: JSON.stringify({ quantity: qty }),
            });
          } else {
            await transfersApi('/api/transfers/' + encodeURIComponent(editTransferId) + '/items', {
              method: 'POST',
              body: JSON.stringify({ product_id: it.product_id, quantity: qty }),
            });
          }
        }
        // Delete lines the user removed while editing the draft.
        for (const oldId of editOriginalItemIds) {
          if (keptIds.indexOf(oldId) === -1) {
            await transfersApi(
              '/api/transfers/' + encodeURIComponent(editTransferId) + '/items/' + encodeURIComponent(oldId),
              { method: 'DELETE' }
            );
          }
        }
        closeCreate();
        toast('Draft updated.', 'success');
        await loadTransfers();
        if (currentTransfer && Number(currentTransfer.id) === Number(editTransferId)) {
          await reloadDetail();
        }
      } else {
        const payload = {
          from_branch_id: Number(fromVal),
          to_branch_id: Number(toVal),
          notes: $('create-notes').value || null,
          items: items,
          client_transfer_id: createClientTransferId,
        };
        const created = await transfersApi('/api/transfers', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        closeCreate();
        toast('Draft ' + created.transfer_number + ' created.', 'success');
        await loadTransfers();
        openDetail(created.id);
      }
    } catch (e) {
      msg.style.display = 'block';
      msg.textContent = (e && e.message) ? e.message : 'Could not save the transfer.';
      if (e && e.status === 409) {
        msg.textContent += ' The transfer may have changed. Refresh the list and try again.';
      }
    } finally {
      busy = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  // ---------- events ----------

  function wireEvents() {
    const backBtn = $('btn-xfer-back');
    if (backBtn) backBtn.addEventListener('click', function () { window.location.href = '/overview'; });
    const logoutBtn = $('btn-xfer-logout');
    if (logoutBtn) logoutBtn.addEventListener('click', function () {
      localStorage.removeItem('pos_token');
      localStorage.removeItem('pos_user');
      window.location.href = '/';
    });

    const newBtn = $('btn-new-transfer');
    if (newBtn) newBtn.addEventListener('click', function () { openCreate(); });
    const refreshBtn = $('btn-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', function () { loadTransfers(); });

    ['filter-status', 'filter-from', 'filter-to'].forEach(function (id) {
      const el = $(id);
      if (el) el.addEventListener('change', function () {
        filters.status = $('filter-status').value;
        filters.from = $('filter-from').value;
        filters.to = $('filter-to').value;
        currentPage = 0;
        loadTransfers();
      });
    });
    const searchEl = $('transfer-search');
    if (searchEl) searchEl.addEventListener('input', function () {
      filters.q = searchEl.value;
      renderList();
    });

    const prevBtn = $('btn-page-prev');
    const nextBtn = $('btn-page-next');
    if (prevBtn) prevBtn.addEventListener('click', function () {
      if (currentPage > 0) { currentPage -= 1; loadTransfers(); }
    });
    if (nextBtn) nextBtn.addEventListener('click', function () {
      currentPage += 1;
      loadTransfers();
    });

    // Delegated list actions (desktop table + mobile cards).
    document.body.addEventListener('click', function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest('button[data-action]') : null;
      if (btn) {
        ev.preventDefault();
        handleAction(btn.getAttribute('data-action'), btn.getAttribute('data-id'));
        return;
      }
      const dbtn = ev.target && ev.target.closest ? ev.target.closest('button[data-detail-action]') : null;
      if (dbtn) {
        ev.preventDefault();
        handleAction(dbtn.getAttribute('data-detail-action'), dbtn.getAttribute('data-id'));
        return;
      }
      const addBtn = ev.target && ev.target.closest ? ev.target.closest('button[data-add-product]') : null;
      if (addBtn) {
        ev.preventDefault();
        addItemToCreate(
          Number(addBtn.getAttribute('data-add-product')),
          addBtn.getAttribute('data-name'),
          addBtn.getAttribute('data-barcode') || null,
          addBtn.getAttribute('data-onhand'),
          addBtn.getAttribute('data-reserved'),
          addBtn.getAttribute('data-available')
        );
        return;
      }
      const rmBtn = ev.target && ev.target.closest ? ev.target.closest('button[data-remove-item]') : null;
      if (rmBtn) {
        ev.preventDefault();
        removeCreateItem(Number(rmBtn.getAttribute('data-remove-item')));
      }
    });
  }

  function wireEventsPart2() {
    const createClose = $('create-close');
    if (createClose) createClose.addEventListener('click', closeCreate);
    const createCancel = $('btn-create-cancel');
    if (createCancel) createCancel.addEventListener('click', closeCreate);
    const searchBtn = $('btn-search-product');
    if (searchBtn) searchBtn.addEventListener('click', function () { searchProducts(); });
    const searchInput = $('create-product-q');
    if (searchInput) searchInput.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); searchProducts(); }
    });
    const saveBtn = $('btn-create-save');
    if (saveBtn) saveBtn.addEventListener('click', function () { submitCreate(); });
    const fromSel = $('create-from');
    if (fromSel) fromSel.addEventListener('change', function () {
      const toSel = $('create-to');
      if (toSel && toSel.value === fromSel.value) {
        const others = branches.filter(function (b) { return String(b.id) !== fromSel.value; });
        if (others.length) toSel.value = String(others[0].id);
        else toSel.value = '';
      }
      createItems.forEach(function (it) { it.on_hand = null; it.reserved = null; it.available = null; });
      renderCreateItems();
      $('product-options').innerHTML = '';
    });

    const detailClose = $('detail-close');
    if (detailClose) detailClose.addEventListener('click', closeDetail);
    const confirmCancel = $('confirm-cancel');
    if (confirmCancel) confirmCancel.addEventListener('click', closeConfirm);

    ['detail-modal', 'create-modal', 'confirm-modal'].forEach(function (id) {
      const modal = $(id);
      if (!modal) return;
      modal.addEventListener('click', function (ev) {
        if (ev.target === modal) {
          if (id === 'detail-modal') closeDetail();
          else if (id === 'create-modal') closeCreate();
          else closeConfirm();
        }
      });
    });
  }

  // ---------- init ----------

  async function init() {
    const ok = await ensureAuthenticated();
    if (!ok) return;
    const canView = hasPerm(PERMS.VIEW) || (user && (user.role === 'admin' || user.role === 'owner'));
    if (!canView) {
      const errBox = $('transfers-error');
      if (errBox) {
        errBox.textContent = '⚠ ' + permissionMessage();
        errBox.style.display = 'block';
      }
      const newBtn = $('btn-new-transfer');
      if (newBtn) newBtn.style.display = 'none';
      return;
    }
    const newBtn = $('btn-new-transfer');
    if (newBtn) {
      newBtn.style.display = hasPerm(PERMS.CREATE) ? 'inline-block' : 'none';
    }
    wireEvents();
    wireEventsPart2();
    await loadBranches();
    await loadTransfers();
  }

  global.StockTransfers = {
    init: init,
    refresh: function () { loadTransfers(); },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);


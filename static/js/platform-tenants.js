(function () {
    const RETURN_PATH = '/platform/tenants';
    const loginWithNext = () => '/?next=' + encodeURIComponent(RETURN_PATH);

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function showGate(message) {
        const gate = document.getElementById('platform-gate');
        const app = document.getElementById('platform-app');
        const msgEl = document.querySelector('.platform-gate-msg');
        const loginA = document.getElementById('platform-gate-login');
        if (msgEl) msgEl.textContent = message;
        if (loginA) loginA.href = loginWithNext();
        if (gate) gate.style.display = 'block';
        if (app) app.style.display = 'none';
    }

    function showApp() {
        const gate = document.getElementById('platform-gate');
        const app = document.getElementById('platform-app');
        if (gate) gate.style.display = 'none';
        if (app) app.style.display = 'block';
    }

    function readSession() {
        const token = localStorage.getItem('pos_token');
        const userStr = localStorage.getItem('pos_user');
        if (!token || !userStr) return { ok: false, reason: 'no_session' };
        try {
            const user = JSON.parse(userStr);
            if (user.role !== 'admin') {
                return { ok: false, reason: 'not_admin' };
            }
            return { ok: true, token, user };
        } catch (e) {
            return { ok: false, reason: 'parse' };
        }
    }

    async function verifyTokenStillValid(token) {
        const res = await fetch('/auth/verify', {
            headers: { Authorization: 'Bearer ' + token },
        });
        return res.ok;
    }

    async function platformFetchJson(url, opts) {
        const token = localStorage.getItem('pos_token');
        const init = Object.assign({ headers: {} }, opts || {});
        init.headers = Object.assign(
            { Accept: 'application/json' },
            init.headers || {},
        );
        if (token) init.headers['Authorization'] = 'Bearer ' + token;
        if (init.body && typeof init.body !== 'string') {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(init.body);
        }
        const res = await fetch(url, init);
        const text = await res.text();
        if (res.status === 401) {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = loginWithNext();
            throw new Error('Unauthorized');
        }
        if (!res.ok) {
            let msg = text || res.statusText;
            try {
                const j = JSON.parse(text);
                if (typeof j.detail === 'string') msg = j.detail;
            } catch (_) {}
            throw new Error(msg.slice(0, 400));
        }
        return text ? JSON.parse(text) : null;
    }

    function parseAdminUsernames(s) {
        if (!s || s === '—') return [];
        return String(s)
            .split(',')
            .map((u) => u.trim())
            .filter((u) => u && u !== '—');
    }

    function renderPlanCell(r) {
        const plan = (r.effective_plan || r.plan || '—').toString();
        const label = plan.charAt(0).toUpperCase() + plan.slice(1);
        const cycle = r.billing_cycle ? ' · ' + escapeHtml(r.billing_cycle) : '';
        const blocked = r.access_allowed === false ? '<br><span style="font-size:11px;color:#b91c1c;">No access</span>' : '';
        return '<span class="pt-badge pt-badge--other">' + escapeHtml(label) + '</span>' + cycle + blocked;
    }

    function renderEndsCell(r) {
        if (r.subscription_end) {
            return '<span style="font-size:12px;">Paid until<br>' + formatDate(r.subscription_end) + '</span>';
        }
        return formatDate(r.trial_ends_at);
    }

    function renderActionsCell(r) {
        const tid = escapeHtml(String(r.id));
        const hasAdmins = parseAdminUsernames(r.admin_usernames).length > 0;
        const resetBtn = hasAdmins
            ? '<button type="button" class="pt-actions-item pt-actions-item--muted js-reset-pw" data-tenant-id="' +
              tid + '">Reset password</button>'
            : '<button type="button" class="pt-actions-item" disabled title="No admin login">Reset password</button>';
        const suspendLabel = r.is_active ? 'Suspend account' : 'Activate account';
        const suspendCls = r.is_active ? 'pt-actions-item--danger js-toggle-tenant' : 'js-toggle-tenant';
        return (
            '<details class="pt-actions-menu">' +
            '<summary class="pt-actions-trigger">Actions</summary>' +
            '<div class="pt-actions-panel">' +
            '<button type="button" class="pt-actions-item js-view-tenant" data-tenant-id="' +
            tid + '">Open details</button>' +
            '<button type="button" class="pt-actions-item js-grant-sub" data-tenant-id="' +
            tid + '">Grant / free access</button>' +
            '<button type="button" class="pt-actions-item pt-actions-item--danger js-revoke-sub" data-tenant-id="' +
            tid + '">Revoke subscription</button>' +
            '<button type="button" class="pt-actions-item ' +
            suspendCls +
            '" data-tenant-id="' +
            tid +
            '">' +
            suspendLabel +
            '</button>' +
            resetBtn +
            '</div></details>'
        );
    }

    // ── Grant subscription modal ─────────────────────────────────────────
    function getGrantModal() {
        return {
            backdrop: document.getElementById('grant-sub-modal-backdrop'),
            business: document.getElementById('grant-sub-modal-business'),
            mode: document.getElementById('grant-sub-mode'),
            plan: document.getElementById('grant-sub-plan'),
            cycle: document.getElementById('grant-sub-cycle'),
            days: document.getElementById('grant-sub-days'),
            daysLabel: document.getElementById('grant-sub-days-label'),
            note: document.getElementById('grant-sub-note'),
            msg: document.getElementById('grant-sub-modal-msg'),
            confirmBtn: document.getElementById('grant-sub-modal-confirm'),
            cancelBtn: document.getElementById('grant-sub-modal-cancel'),
        };
    }

    function setGrantModalMessage(text, kind) {
        const m = getGrantModal();
        if (!m.msg) return;
        m.msg.textContent = text || '';
        m.msg.classList.remove('error', 'success');
        if (kind) m.msg.classList.add(kind);
    }

    function syncGrantDaysField() {
        const m = getGrantModal();
        if (!m.mode || !m.days || !m.daysLabel) return;
        const mode = m.mode.value;
        const isTrial = mode === 'trial';
        const isComp = mode === 'complimentary';
        const reason = document.getElementById('grant-sub-reason');
        const reasonLabel = document.getElementById('grant-sub-reason-label');
        if (reason) reason.style.display = isComp ? '' : 'none';
        if (reasonLabel) reasonLabel.style.display = isComp ? '' : 'none';
        m.daysLabel.textContent = isTrial
            ? 'Trial length (days)'
            : isComp
              ? 'Duration (days; leave 0 for permanent)'
              : 'Duration (days)';
        m.days.max = isTrial ? '365' : '3650';
        if (isTrial) m.days.value = '14';
        else if (isComp) m.days.value = '0';
        else m.days.value = m.cycle && m.cycle.value === 'yearly' ? '365' : '30';
        if (m.cycle) m.cycle.disabled = isTrial || isComp;
    }

    function closeGrantModal() {
        const m = getGrantModal();
        if (!m.backdrop) return;
        m.backdrop.classList.remove('visible');
        setGrantModalMessage('');
    }

    function openGrantModal(row) {
        const m = getGrantModal();
        if (!m.backdrop) return;
        if (m.business) m.business.textContent = row.business_name || '—';
        if (m.plan) m.plan.value = row.effective_plan || row.plan || 'pro';
        if (m.mode) m.mode.value = (row.billing_status || row.subscription_status) === 'trial' ? 'trial' : 'active';
        syncGrantDaysField();
        if (m.note) m.note.value = '';
        setGrantModalMessage('');
        m.backdrop.classList.add('visible');
        if (m.plan) m.plan.focus();
    }

    async function submitGrantModal() {
        const m = getGrantModal();
        const tenantId = m.backdrop && m.backdrop.dataset.tenantId;
        if (!tenantId) return;
        const mode = m.mode ? m.mode.value : 'active';
        const days = m.days ? parseInt(m.days.value, 10) : 30;
        const note = m.note && m.note.value.trim() ? m.note.value.trim() : null;
        const plan = m.plan ? m.plan.value : 'pro';
        if (m.confirmBtn) m.confirmBtn.disabled = true;
        setGrantModalMessage('Saving…', '');
        try {
            if (mode === 'complimentary') {
                const reasonEl = document.getElementById('grant-sub-reason');
                const permanent = !days || days <= 0;
                await platformFetchJson('/api/platform/complimentary-grants', {
                    method: 'POST',
                    body: {
                        tenant_id: parseInt(tenantId, 10),
                        plan: plan,
                        reason: reasonEl ? reasonEl.value : 'support',
                        note: note,
                        permanent: permanent,
                        duration_days: permanent ? null : days,
                    },
                });
                setGrantModalMessage('Complimentary access granted.', 'success');
            } else {
                await platformFetchJson('/api/platform/tenants/' + tenantId + '/subscription/grant', {
                    method: 'POST',
                    body: {
                        plan: plan,
                        billing_cycle: m.cycle ? m.cycle.value : 'monthly',
                        grant_mode: mode,
                        trial_days: days || 14,
                        duration_days: days || 30,
                        note: note,
                    },
                });
                setGrantModalMessage('Subscription updated.', 'success');
            }
            closeGrantModal();
            await loadTenants();
            if (typeof loadGrants === 'function') await loadGrants();
        } catch (e) {
            setGrantModalMessage(e.message || 'Grant failed', 'error');
        } finally {
            if (m.confirmBtn) m.confirmBtn.disabled = false;
        }
    }

    async function revokeSubscription(row) {
        const name = row.business_name || 'this business';
        if (
            !confirm(
                'Revoke subscription for “' +
                    name +
                    '”? They will lose access until you grant again.',
            )
        ) {
            return;
        }
        try {
            await platformFetchJson('/api/platform/tenants/' + row.id + '/subscription/revoke', {
                method: 'POST',
                body: { reason: 'Revoked from platform tenants page' },
            });
            await loadTenants();
        } catch (e) {
            alert(e.message || 'Revoke failed');
        }
    }

    function wireGrantModal() {
        const m = getGrantModal();
        if (!m.backdrop) return;
        if (m.cancelBtn) m.cancelBtn.addEventListener('click', closeGrantModal);
        if (m.confirmBtn) m.confirmBtn.addEventListener('click', submitGrantModal);
        if (m.mode) m.mode.addEventListener('change', syncGrantDaysField);
        if (m.cycle) m.cycle.addEventListener('change', syncGrantDaysField);
        m.backdrop.addEventListener('click', (e) => {
            if (e.target === m.backdrop) closeGrantModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && m.backdrop.classList.contains('visible')) {
                closeGrantModal();
            }
        });
    }

    let _actionsMenuOutsideListener = false;

    function closeAllActionsMenus(body) {
        body.querySelectorAll('.pt-actions-menu[open]').forEach((menu) => menu.removeAttribute('open'));
    }

    function wireTenantActionButtons(body) {
        if (!_actionsMenuOutsideListener) {
            _actionsMenuOutsideListener = true;
            document.addEventListener(
                'click',
                (e) => {
                    const tbody = document.getElementById('platform-tenants-body');
                    if (!tbody || e.target.closest('.pt-actions-menu')) return;
                    closeAllActionsMenus(tbody);
                },
                true
            );
        }

        body.querySelectorAll('.pt-actions-menu').forEach((menu) => {
            menu.addEventListener('toggle', () => {
                if (!menu.open) return;
                body.querySelectorAll('.pt-actions-menu[open]').forEach((other) => {
                    if (other !== menu) other.removeAttribute('open');
                });
            });
        });

        body.querySelectorAll('button.js-grant-sub').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                closeAllActionsMenus(body);
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (!row) return;
                const m = getGrantModal();
                if (m.backdrop) m.backdrop.dataset.tenantId = id;
                openGrantModal(row);
            });
        });
        body.querySelectorAll('button.js-revoke-sub').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                closeAllActionsMenus(body);
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (row) revokeSubscription(row);
            });
        });
        body.querySelectorAll('button.js-reset-pw').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                closeAllActionsMenus(body);
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (row) openResetModal(row);
            });
        });
        body.querySelectorAll('button.js-view-tenant').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                closeAllActionsMenus(body);
                const id = btn.getAttribute('data-tenant-id');
                if (id) openTenantDetail(id);
            });
        });
        body.querySelectorAll('button.js-toggle-tenant').forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                closeAllActionsMenus(body);
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (!row) return;
                const activate = !row.is_active;
                const label = activate ? 'Activate' : 'Suspend';
                if (!confirm(label + ' account “' + (row.business_name || id) + '”?')) return;
                try {
                    await platformFetchJson(
                        '/api/platform/tenants/' + id + '/' + (activate ? 'activate' : 'suspend'),
                        { method: 'POST', body: { reason: label + ' from platform console' } },
                    );
                    await loadTenants();
                } catch (err) {
                    alert(err.message || 'Action failed');
                }
            });
        });
    }

    // ── Reset-password modal ──────────────────────────────────────────────
    function getResetModal() {
        return {
            backdrop: document.getElementById('reset-pw-modal-backdrop'),
            business: document.getElementById('reset-pw-modal-business'),
            select: document.getElementById('reset-pw-modal-username'),
            free: document.getElementById('reset-pw-modal-username-free'),
            newpw: document.getElementById('reset-pw-modal-newpw'),
            confirm: document.getElementById('reset-pw-modal-confirm'),
            msg: document.getElementById('reset-pw-modal-msg'),
            confirmBtn: document.getElementById('reset-pw-modal-confirm-btn'),
            cancelBtn: document.getElementById('reset-pw-modal-cancel'),
        };
    }

    function setModalMessage(text, kind) {
        const m = getResetModal();
        if (!m.msg) return;
        m.msg.textContent = text || '';
        m.msg.classList.remove('error', 'success');
        if (kind) m.msg.classList.add(kind);
    }

    function closeResetModal() {
        const m = getResetModal();
        if (!m.backdrop) return;
        m.backdrop.classList.remove('visible');
        if (m.newpw) m.newpw.value = '';
        if (m.confirm) m.confirm.value = '';
        if (m.free) m.free.value = '';
        setModalMessage('');
        if (m.confirmBtn) {
            m.confirmBtn.disabled = false;
            m.confirmBtn.textContent = 'Reset password';
        }
    }

    function openResetModal(row) {
        const m = getResetModal();
        if (!m.backdrop) return;
        const usernames = parseAdminUsernames(row.admin_usernames);
        m.business.textContent =
            row.business_name + (row.email ? ' · ' + row.email : '');

        m.select.innerHTML = '';
        if (usernames.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '— no admin logins on file —';
            opt.disabled = true;
            opt.selected = true;
            m.select.appendChild(opt);
            m.select.disabled = true;
        } else {
            m.select.disabled = false;
            usernames.forEach((u, idx) => {
                const opt = document.createElement('option');
                opt.value = u;
                opt.textContent = u;
                if (idx === 0) opt.selected = true;
                m.select.appendChild(opt);
            });
        }

        setModalMessage('');
        m.newpw.value = '';
        m.confirm.value = '';
        m.free.value = '';
        m.confirmBtn.disabled = false;
        m.confirmBtn.textContent = 'Reset password';
        m.backdrop.classList.add('visible');
        setTimeout(() => m.newpw && m.newpw.focus(), 0);
    }

    function validateResetForm() {
        const m = getResetModal();
        const free = (m.free.value || '').trim();
        const usernameOrEmail = free || (m.select.value || '').trim();
        if (!usernameOrEmail) {
            return { error: 'Pick an admin login or type a username/email.' };
        }
        const pw = m.newpw.value || '';
        if (pw.length < 8) {
            return { error: 'Password must be at least 8 characters.' };
        }
        if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) {
            return { error: 'Password must contain both letters and numbers.' };
        }
        if (pw !== m.confirm.value) {
            return { error: 'Passwords do not match.' };
        }
        // Decide which field to send: emails go to `email`, anything else to `username`.
        const payload = { new_password: pw };
        if (usernameOrEmail.includes('@')) payload.email = usernameOrEmail;
        else payload.username = usernameOrEmail;
        return { payload };
    }

    async function submitResetForm() {
        const m = getResetModal();
        setModalMessage('');
        const v = validateResetForm();
        if (v.error) {
            setModalMessage(v.error, 'error');
            return;
        }
        m.confirmBtn.disabled = true;
        m.confirmBtn.textContent = 'Resetting…';
        try {
            const res = await platformFetchJson(
                '/api/platform/reset-user-password',
                { method: 'POST', body: v.payload },
            );
            const who = res && res.username ? res.username : 'user';
            setModalMessage(
                `Done. ${who}'s password was reset. ` +
                    `${res && res.refresh_tokens_revoked || 0} old session(s) revoked.`,
                'success',
            );
            m.confirmBtn.textContent = 'Done';
            setTimeout(closeResetModal, 1800);
        } catch (e) {
            if (e && e.message === 'Unauthorized') return;
            setModalMessage(e.message || 'Reset failed.', 'error');
            m.confirmBtn.disabled = false;
            m.confirmBtn.textContent = 'Reset password';
        }
    }

    function wireResetModal() {
        const m = getResetModal();
        if (!m.backdrop) return;
        if (m.cancelBtn) m.cancelBtn.addEventListener('click', closeResetModal);
        if (m.confirmBtn) m.confirmBtn.addEventListener('click', submitResetForm);
        m.backdrop.addEventListener('click', (e) => {
            if (e.target === m.backdrop) closeResetModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && m.backdrop.classList.contains('visible')) {
                closeResetModal();
            }
        });
    }

    function formatDate(iso) {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
            });
        } catch (_) {
            return iso;
        }
    }

    function statusBadgeClass(status) {
        const s = (status || '').toLowerCase();
        if (s === 'trial') return 'pt-badge--trial';
        if (s === 'complimentary') return 'pt-badge--complimentary';
        if (s === 'active' || s === 'paid') return 'pt-badge--active';
        if (s === 'suspended') return 'pt-badge--expired';
        if (s.includes('expired') || s === 'canceled') return 'pt-badge--expired';
        return 'pt-badge--other';
    }

    function renderStatusCell(r) {
        const status = escapeHtml(r.subscription_status || '—');
        const badgeCls = statusBadgeClass(r.subscription_status);
        const dotCls = r.is_active ? 'pt-active-dot--yes' : 'pt-active-dot--no';
        const activeLabel = r.is_active ? 'Active' : 'Inactive';
        return (
            '<span class="pt-badge ' + badgeCls + '">' + status + '</span>' +
            '<br><span style="margin-top:4px;display:inline-block;font-size:12px;color:rgba(26,26,26,0.65);">' +
            '<span class="pt-active-dot ' + dotCls + '" aria-hidden="true"></span>' +
            escapeHtml(activeLabel) +
            '</span>'
        );
    }

    function renderBusinessCell(r) {
        const name = escapeHtml(r.business_name);
        if (r.store_display_name && r.store_display_name !== r.business_name) {
            return name + '<span class="platform-subname">' + escapeHtml(r.store_display_name) + '</span>';
        }
        return name;
    }

    function applyOverviewStats(data) {
        const t = (data && data.totals) || {};
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val == null ? '—' : String(val);
        };
        set('stat-total', t.businesses);
        set('stat-users', t.users);
        set('stat-stores', t.stores);
        set('stat-active', t.active_accounts);
        set('stat-suspended', t.suspended_accounts);
        set('stat-trial', t.trial_accounts);
        set('stat-paid', t.paid_subscriptions);
        set('stat-comp', t.complimentary_accounts);
        set('stat-expired', t.expired_subscriptions);

        const regs = document.getElementById('overview-recent-regs');
        if (regs) {
            const list = (data && data.recent_registrations) || [];
            regs.innerHTML = list.length
                ? list
                      .map(
                          (r) =>
                              '<div><strong>' +
                              escapeHtml(r.business_name) +
                              '</strong> · ' +
                              escapeHtml(r.email || '—') +
                              ' · ' +
                              formatDate(r.created_at) +
                              '</div>',
                      )
                      .join('')
                : 'No recent registrations.';
        }
        const billing = document.getElementById('overview-recent-billing');
        if (billing) {
            const list = (data && data.recent_subscription_changes) || [];
            billing.innerHTML = list.length
                ? list
                      .map(
                          (e) =>
                              '<div><strong>' +
                              escapeHtml(e.event_type) +
                              '</strong> · ' +
                              escapeHtml(e.business_name || 'tenant #' + e.tenant_id) +
                              ' · ' +
                              formatDate(e.created_at) +
                              '<br><span style="color:#64748b;">' +
                              escapeHtml(e.description || '') +
                              '</span></div>',
                      )
                      .join('')
                : 'No recent billing events.';
        }
    }

    async function loadOverview() {
        const data = await platformFetchJson('/api/platform/overview');
        applyOverviewStats(data);
    }

    // Most recent /api/platform/tenants response, keyed by tenant id, so the
    // per-row "Reset password" handler can look up the tenant without
    // re-parsing the DOM (and without trusting attributes for sensitive data).
    const _tenantsById = new Map();

    let _allTenants = [];

    async function loadTenants() {
        const errEl = document.getElementById('platform-error');
        const loadingEl = document.getElementById('platform-loading');
        const tableWrap = document.getElementById('platform-table-container');
        const body = document.getElementById('platform-tenants-body');
        const refreshBtn = document.getElementById('platform-refresh-btn');

        if (errEl) errEl.style.display = 'none';
        if (loadingEl) loadingEl.style.display = 'flex';
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const rows = await platformFetchJson('/api/platform/tenants');
            if (loadingEl) loadingEl.style.display = 'none';
            _tenantsById.clear();
            _allTenants = Array.isArray(rows) ? rows : [];
            renderTenantRows(_allTenants);
            renderSubscriptionsTable(_allTenants);
            if (tableWrap) tableWrap.style.display = 'block';
        } catch (e) {
            if (loadingEl) loadingEl.style.display = 'none';
            if (e && e.message === 'Unauthorized') return;
            if (errEl) {
                errEl.textContent =
                    e.message ||
                    'Could not load businesses. If you are the platform owner, set PLATFORM_OWNER_EMAILS on the server to include your account email.';
                errEl.style.display = 'block';
            }
        } finally {
            if (refreshBtn) refreshBtn.disabled = false;
        }
    }

    function renderTenantRows(rows) {
        const body = document.getElementById('platform-tenants-body');
        if (!body) return;
        const q = ((document.getElementById('business-search') || {}).value || '')
            .trim()
            .toLowerCase();
        let filtered = rows;
        if (q) {
            filtered = rows.filter((r) => {
                const hay = [
                    r.business_name,
                    r.owner_name,
                    r.email,
                    r.phone,
                    r.tenant_uid,
                    String(r.id),
                    r.admin_usernames,
                ]
                    .join(' ')
                    .toLowerCase();
                return hay.includes(q);
            });
        }
        _tenantsById.clear();
        filtered.forEach((r) => _tenantsById.set(String(r.id), r));
        if (!filtered.length) {
            body.innerHTML =
                '<tr><td colspan="10"><div class="platform-empty"><strong>No matching businesses</strong></div></td></tr>';
            return;
        }
        body.innerHTML = filtered
            .map((r) => {
                const contact = [r.email, r.phone].filter(Boolean).join(' · ') || '—';
                return (
                    '<tr>' +
                    '<td class="col-business">' +
                    renderBusinessCell(r) +
                    '<div class="platform-subname">ID ' +
                    escapeHtml(String(r.id)) +
                    ' · ' +
                    escapeHtml(r.tenant_uid || '') +
                    '</div></td>' +
                    '<td class="col-owner">' +
                    (escapeHtml(r.owner_name) || '—') +
                    '</td>' +
                    '<td class="col-contact">' +
                    escapeHtml(contact) +
                    '</td>' +
                    '<td>' +
                    renderStatusCell(r) +
                    '</td>' +
                    '<td class="col-plan">' +
                    renderPlanCell(r) +
                    '</td>' +
                    '<td class="col-date">' +
                    renderEndsCell(r) +
                    '</td>' +
                    '<td class="col-num">' +
                    escapeHtml(String(r.user_count)) +
                    '</td>' +
                    '<td class="col-num">' +
                    escapeHtml(String(r.store_count != null ? r.store_count : '—')) +
                    '</td>' +
                    '<td class="col-admins">' +
                    escapeHtml(r.admin_usernames) +
                    '</td>' +
                    '<td class="col-actions">' +
                    renderActionsCell(r) +
                    '</td>' +
                    '</tr>'
                );
            })
            .join('');
        wireTenantActionButtons(body);
    }

    function renderSubscriptionsTable(rows) {
        const body = document.getElementById('platform-subs-body');
        if (!body) return;
        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="7"><div class="platform-empty">No subscriptions</div></td></tr>';
            return;
        }
        body.innerHTML = rows
            .map((r) => {
                return (
                    '<tr>' +
                    '<td>' +
                    escapeHtml(r.business_name) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(r.effective_plan || r.plan || '—') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(r.billing_status || '—') +
                    '</td>' +
                    '<td><span class="pt-badge ' +
                    statusBadgeClass(r.subscription_status) +
                    '">' +
                    escapeHtml(r.subscription_status || '—') +
                    '</span></td>' +
                    '<td>' +
                    escapeHtml(r.entitlement_source || '—') +
                    '</td>' +
                    '<td>' +
                    renderEndsCell(r) +
                    '</td>' +
                    '<td>' +
                    (r.access_allowed === false ? 'Blocked' : 'Allowed') +
                    '</td>' +
                    '</tr>'
                );
            })
            .join('');
    }

    async function openTenantDetail(tenantId) {
        const panel = document.getElementById('tenant-detail');
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = '<p class="platform-kv">Loading account details…</p>';
        try {
            const d = await platformFetchJson('/api/platform/tenants/' + tenantId);
            const t = d.tenant || {};
            const sub = d.subscription || {};
            panel.innerHTML =
                '<h3>' +
                escapeHtml(t.business_name || 'Business') +
                '</h3>' +
                '<div class="platform-kv">' +
                '<div><strong>ID:</strong> ' +
                escapeHtml(String(t.id)) +
                ' · <strong>UID:</strong> ' +
                escapeHtml(t.tenant_uid || '') +
                '</div>' +
                '<div><strong>Owner:</strong> ' +
                escapeHtml(t.owner_name || '—') +
                ' · <strong>Email:</strong> ' +
                escapeHtml(t.email || '—') +
                '</div>' +
                '<div><strong>Account:</strong> ' +
                (t.is_active ? 'Active' : 'Suspended') +
                ' · <strong>Effective:</strong> ' +
                escapeHtml(sub.effective_status || '—') +
                ' · <strong>Source:</strong> ' +
                escapeHtml(sub.entitlement_source || '—') +
                '</div>' +
                '<div><strong>Plan:</strong> ' +
                escapeHtml(sub.effective_plan || sub.plan || '—') +
                ' · <strong>Access:</strong> ' +
                (sub.access_allowed ? 'Allowed' : 'Blocked') +
                '</div>' +
                '<div style="margin-top:10px;"><strong>Users (' +
                (d.users || []).length +
                ')</strong><br>' +
                (d.users || [])
                    .map(
                        (u) =>
                            escapeHtml(u.full_name || u.username) +
                            ' &lt;' +
                            escapeHtml(u.email || u.username) +
                            '&gt; · ' +
                            escapeHtml(u.role) +
                            (u.is_active ? '' : ' (inactive)'),
                    )
                    .join('<br>') +
                '</div>' +
                '<div style="margin-top:10px;"><strong>Stores (' +
                (d.stores || []).length +
                ')</strong><br>' +
                ((d.stores || []).length
                    ? (d.stores || [])
                          .map(
                              (s) =>
                                  escapeHtml(s.name) +
                                  (s.address ? ' — ' + escapeHtml(s.address) : '') +
                                  (s.is_active ? '' : ' (inactive)'),
                          )
                          .join('<br>')
                    : 'No stores') +
                '</div>' +
                '<div style="margin-top:10px;"><strong>Complimentary grants</strong><br>' +
                ((d.complimentary_grants || []).length
                    ? (d.complimentary_grants || [])
                          .slice(0, 8)
                          .map(
                              (g) =>
                                  '#' +
                                  g.id +
                                  ' ' +
                                  escapeHtml(g.plan) +
                                  ' · ' +
                                  escapeHtml(g.reason) +
                                  ' · ' +
                                  (g.active ? 'active' : 'inactive') +
                                  (g.permanent ? ' · permanent' : ''),
                          )
                          .join('<br>')
                    : 'None') +
                '</div>' +
                '<div style="margin-top:10px;"><strong>History</strong><br>' +
                ((d.billing_history || []).length
                    ? (d.billing_history || [])
                          .slice(0, 10)
                          .map(
                              (e) =>
                                  formatDate(e.created_at) +
                                  ' · ' +
                                  escapeHtml(e.event_type) +
                                  ' — ' +
                                  escapeHtml(e.description || ''),
                          )
                          .join('<br>')
                    : 'No events') +
                '</div></div>';
        } catch (e) {
            panel.innerHTML = '<p class="platform-kv" style="color:#b91c1c;">' + escapeHtml(e.message) + '</p>';
        }
    }

    async function loadUsers() {
        const q = ((document.getElementById('users-search') || {}).value || '').trim();
        const status = ((document.getElementById('users-status') || {}).value || '').trim();
        const params = new URLSearchParams({ page: '1', page_size: '100' });
        if (q) params.set('q', q);
        if (status) params.set('status', status);
        const data = await platformFetchJson('/api/platform/users?' + params.toString());
        const body = document.getElementById('platform-users-body');
        if (!body) return;
        const items = data.items || [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="8"><div class="platform-empty">No users found</div></td></tr>';
            return;
        }
        body.innerHTML = items
            .map((u) => {
                const suspendBtn = u.is_active
                    ? '<button type="button" class="platform-btn platform-btn--secondary js-user-suspend" data-id="' +
                      u.id +
                      '" style="min-height:32px;padding:0 10px;">Suspend</button>'
                    : '<button type="button" class="platform-btn platform-btn--secondary js-user-activate" data-id="' +
                      u.id +
                      '" style="min-height:32px;padding:0 10px;">Activate</button>';
                return (
                    '<tr>' +
                    '<td>' +
                    escapeHtml(u.full_name || '—') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(u.email || '—') +
                    '<div class="platform-subname">' +
                    escapeHtml(u.username) +
                    '</div></td>' +
                    '<td>' +
                    escapeHtml(u.business_name || '—') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(u.role) +
                    '</td>' +
                    '<td>' +
                    (u.is_active ? 'Active' : 'Inactive') +
                    '</td>' +
                    '<td>' +
                    formatDate(u.created_at) +
                    '</td>' +
                    '<td>' +
                    formatDate(u.last_login) +
                    '</td>' +
                    '<td>' +
                    suspendBtn +
                    '</td>' +
                    '</tr>'
                );
            })
            .join('');
        body.querySelectorAll('.js-user-suspend').forEach((btn) => {
            btn.addEventListener('click', async () => {
                if (!confirm('Suspend this user?')) return;
                await platformFetchJson('/api/platform/users/' + btn.dataset.id + '/suspend', {
                    method: 'POST',
                    body: { reason: 'Suspended from platform console' },
                });
                await loadUsers();
            });
        });
        body.querySelectorAll('.js-user-activate').forEach((btn) => {
            btn.addEventListener('click', async () => {
                await platformFetchJson('/api/platform/users/' + btn.dataset.id + '/activate', {
                    method: 'POST',
                    body: { reason: 'Activated from platform console' },
                });
                await loadUsers();
            });
        });
    }

    async function loadStores() {
        const q = ((document.getElementById('stores-search') || {}).value || '').trim();
        const params = new URLSearchParams({ page: '1', page_size: '100' });
        if (q) params.set('q', q);
        const data = await platformFetchJson('/api/platform/branches?' + params.toString());
        const body = document.getElementById('platform-stores-body');
        if (!body) return;
        const items = data.items || [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="6"><div class="platform-empty">No stores found</div></td></tr>';
            return;
        }
        body.innerHTML = items
            .map(
                (s) =>
                    '<tr>' +
                    '<td>' +
                    escapeHtml(s.name) +
                    (s.code ? '<div class="platform-subname">' + escapeHtml(s.code) + '</div>' : '') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(s.business_name || '—') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(s.address || '—') +
                    '</td>' +
                    '<td>' +
                    (s.is_active ? 'Active' : 'Inactive') +
                    (s.is_default ? ' · Main' : '') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(s.manager_username || '—') +
                    '</td>' +
                    '<td>' +
                    formatDate(s.created_at) +
                    '</td>' +
                    '</tr>',
            )
            .join('');
    }

    async function loadGrants() {
        const activeOnly = !!(document.getElementById('grants-active-only') || {}).checked;
        const params = new URLSearchParams({ page: '1', page_size: '100' });
        if (activeOnly) params.set('active_only', 'true');
        const data = await platformFetchJson('/api/platform/complimentary-grants?' + params.toString());
        const body = document.getElementById('platform-grants-body');
        if (!body) return;
        const items = data.items || [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="8"><div class="platform-empty">No complimentary grants</div></td></tr>';
            return;
        }
        body.innerHTML = items
            .map((g) => {
                const actions = g.active
                    ? '<button type="button" class="platform-btn platform-btn--secondary js-extend-grant" data-id="' +
                      g.id +
                      '" style="min-height:32px;padding:0 8px;margin-right:4px;">Extend</button>' +
                      '<button type="button" class="platform-btn platform-btn--secondary js-revoke-grant" data-id="' +
                      g.id +
                      '" style="min-height:32px;padding:0 8px;color:#b91c1c;">Revoke</button>'
                    : '—';
                return (
                    '<tr>' +
                    '<td>' +
                    escapeHtml(g.business_name || 'tenant #' + g.tenant_id) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(g.plan) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(g.reason) +
                    (g.note ? '<div class="platform-subname">' + escapeHtml(g.note) + '</div>' : '') +
                    '</td>' +
                    '<td>' +
                    formatDate(g.starts_at) +
                    '</td>' +
                    '<td>' +
                    (g.permanent ? 'Permanent' : formatDate(g.ends_at)) +
                    '</td>' +
                    '<td>' +
                    (g.active
                        ? '<span class="pt-badge pt-badge--complimentary">Active</span>'
                        : g.revoked_at
                          ? 'Revoked'
                          : 'Expired') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(g.granted_by_username || '—') +
                    '</td>' +
                    '<td>' +
                    actions +
                    '</td>' +
                    '</tr>'
                );
            })
            .join('');
        body.querySelectorAll('.js-revoke-grant').forEach((btn) => {
            btn.addEventListener('click', async () => {
                if (!confirm('Revoke this complimentary grant? Access will stop immediately.')) return;
                await platformFetchJson('/api/platform/complimentary-grants/' + btn.dataset.id + '/revoke', {
                    method: 'POST',
                    body: { reason: 'Revoked from platform console' },
                });
                await loadGrants();
                await loadTenants();
            });
        });
        body.querySelectorAll('.js-extend-grant').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const days = prompt('Extend by how many days? (or type permanent)', '30');
                if (days == null) return;
                const bodyPayload =
                    String(days).toLowerCase() === 'permanent'
                        ? { permanent: true, note: 'Extended to permanent' }
                        : { duration_days: parseInt(days, 10) || 30, note: 'Extended from platform console' };
                await platformFetchJson('/api/platform/complimentary-grants/' + btn.dataset.id + '/extend', {
                    method: 'POST',
                    body: bodyPayload,
                });
                await loadGrants();
            });
        });
    }

    async function loadPayments() {
        const data = await platformFetchJson('/api/platform/payments?page=1&page_size=100');
        const body = document.getElementById('platform-payments-body');
        if (!body) return;
        const items = data.items || [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="7"><div class="platform-empty">No payment records</div></td></tr>';
            return;
        }
        body.innerHTML = items
            .map(
                (p) =>
                    '<tr>' +
                    '<td>' +
                    escapeHtml(p.business_name || '—') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(p.payment_reference) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(String(p.amount != null ? p.amount : '—')) +
                    ' ' +
                    escapeHtml(p.currency || '') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(p.status) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(p.plan || '—') +
                    '</td>' +
                    '<td>' +
                    formatDate(p.created_at) +
                    '</td>' +
                    '<td>' +
                    formatDate(p.paid_at) +
                    '</td>' +
                    '</tr>',
            )
            .join('');
    }

    async function loadAudit() {
        const data = await platformFetchJson('/api/platform/audit-logs?page=1&page_size=100');
        const body = document.getElementById('platform-audit-body');
        if (!body) return;
        const items = data.items || [];
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="6"><div class="platform-empty">No platform audit entries yet</div></td></tr>';
            return;
        }
        body.innerHTML = items
            .map(
                (r) =>
                    '<tr>' +
                    '<td>' +
                    formatDate(r.created_at) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(r.username || '—') +
                    '</td>' +
                    '<td>' +
                    escapeHtml(r.action) +
                    '</td>' +
                    '<td>' +
                    escapeHtml(r.entity_type) +
                    (r.entity_id != null ? ' #' + r.entity_id : '') +
                    '</td>' +
                    '<td>' +
                    (r.tenant_id != null ? String(r.tenant_id) : '—') +
                    '</td>' +
                    '<td style="max-width:280px;white-space:normal;font-size:12px;">' +
                    escapeHtml((r.new_value || r.old_value || '').toString().slice(0, 180)) +
                    '</td>' +
                    '</tr>',
            )
            .join('');
    }

    async function loadSettings() {
        const data = await platformFetchJson('/api/platform/settings');
        const el = document.getElementById('platform-settings-body');
        if (!el) return;
        el.innerHTML =
            '<div>' +
            escapeHtml(data.note || '') +
            '</div>' +
            '<div style="margin-top:10px;"><strong>Owner emails configured:</strong> ' +
            (data.platform_owner_emails_configured ? 'yes (' + data.platform_owner_email_count + ')' : 'no') +
            '</div>' +
            '<div><strong>Owner usernames configured:</strong> ' +
            (data.platform_owner_usernames_configured
                ? 'yes (' + data.platform_owner_username_count + ')'
                : 'no') +
            '</div>' +
            '<div><strong>Complimentary reasons:</strong> ' +
            escapeHtml((data.complimentary_reasons || []).join(', ')) +
            '</div>' +
            '<div><strong>Plans:</strong> ' +
            escapeHtml((data.plans || []).join(', ')) +
            '</div>';
    }

    function showSection(name) {
        document.querySelectorAll('.platform-section').forEach((s) => s.classList.remove('active'));
        document.querySelectorAll('.js-platform-nav').forEach((b) => b.classList.remove('active'));
        const section = document.getElementById('section-' + name);
        if (section) section.classList.add('active');
        document.querySelectorAll('.js-platform-nav[data-section="' + name + '"]').forEach((b) => {
            b.classList.add('active');
        });
    }

    async function loadSection(name) {
        showSection(name);
        const loadingEl = document.getElementById('platform-loading');
        if (loadingEl) loadingEl.style.display = 'flex';
        try {
            if (name === 'overview') await loadOverview();
            else if (name === 'businesses' || name === 'subscriptions') await loadTenants();
            else if (name === 'users') await loadUsers();
            else if (name === 'stores') await loadStores();
            else if (name === 'grants') await loadGrants();
            else if (name === 'payments') await loadPayments();
            else if (name === 'audit') await loadAudit();
            else if (name === 'settings') await loadSettings();
        } catch (e) {
            if (e && e.message === 'Unauthorized') return;
            const errEl = document.getElementById('platform-error');
            if (errEl) {
                errEl.textContent = e.message || 'Load failed';
                errEl.style.display = 'block';
            }
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    function wireCompGrantModal() {
        const backdrop = document.getElementById('comp-grant-modal-backdrop');
        const cancel = document.getElementById('comp-grant-modal-cancel');
        const confirmBtn = document.getElementById('comp-grant-modal-confirm');
        const openBtn = document.getElementById('open-comp-grant-btn');
        const msg = document.getElementById('comp-grant-modal-msg');
        const close = () => {
            if (backdrop) backdrop.classList.remove('visible');
            if (msg) {
                msg.textContent = '';
                msg.classList.remove('error', 'success');
            }
        };
        if (openBtn) {
            openBtn.addEventListener('click', () => {
                if (backdrop) backdrop.classList.add('visible');
            });
        }
        if (cancel) cancel.addEventListener('click', close);
        if (backdrop) {
            backdrop.addEventListener('click', (e) => {
                if (e.target === backdrop) close();
            });
        }
        if (confirmBtn) {
            confirmBtn.addEventListener('click', async () => {
                const tenantId = parseInt((document.getElementById('comp-grant-tenant') || {}).value, 10);
                if (!tenantId) {
                    if (msg) {
                        msg.textContent = 'Enter a business ID.';
                        msg.classList.add('error');
                    }
                    return;
                }
                const duration = (document.getElementById('comp-grant-duration') || {}).value || 'permanent';
                const permanent = duration === 'permanent';
                confirmBtn.disabled = true;
                try {
                    await platformFetchJson('/api/platform/complimentary-grants', {
                        method: 'POST',
                        body: {
                            tenant_id: tenantId,
                            plan: (document.getElementById('comp-grant-plan') || {}).value || 'pro',
                            reason: (document.getElementById('comp-grant-reason') || {}).value || 'support',
                            note: ((document.getElementById('comp-grant-note') || {}).value || '').trim() || null,
                            permanent: permanent,
                            duration_days: permanent ? null : parseInt(duration, 10),
                        },
                    });
                    if (msg) {
                        msg.textContent = 'Grant created.';
                        msg.classList.remove('error');
                        msg.classList.add('success');
                    }
                    close();
                    await loadGrants();
                    await loadTenants();
                } catch (e) {
                    if (msg) {
                        msg.textContent = e.message || 'Failed';
                        msg.classList.add('error');
                    }
                } finally {
                    confirmBtn.disabled = false;
                }
            });
        }
    }

    window.addEventListener('load', async () => {
        const session = readSession();
        if (!session.ok) {
            if (session.reason === 'not_admin') {
                showGate('This page is only for administrator accounts. Sign in with a store admin login.');
            } else {
                showGate('Sign in as an administrator on this site to view all businesses.');
            }
            return;
        }

        const el = document.getElementById('platform-user-info');
        if (el) el.textContent = `${session.user.username} (${session.user.role})`;

        showApp();

        const stillValid = await verifyTokenStillValid(session.token);
        if (!stillValid) {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            showGate('Your session expired or is invalid. Sign in again.');
            return;
        }

        wireResetModal();
        wireGrantModal();
        wireCompGrantModal();

        document.querySelectorAll('.js-platform-nav').forEach((btn) => {
            btn.addEventListener('click', () => loadSection(btn.getAttribute('data-section')));
        });

        const refreshBtn = document.getElementById('platform-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                const active = document.querySelector('.js-platform-nav.active');
                loadSection(active ? active.getAttribute('data-section') : 'overview');
            });
        }

        const bizSearch = document.getElementById('business-search');
        if (bizSearch) {
            bizSearch.addEventListener('input', () => renderTenantRows(_allTenants));
        }
        const usersBtn = document.getElementById('users-search-btn');
        if (usersBtn) usersBtn.addEventListener('click', () => loadUsers());
        const storesBtn = document.getElementById('stores-search-btn');
        if (storesBtn) storesBtn.addEventListener('click', () => loadStores());
        const grantsRefresh = document.getElementById('grants-refresh-btn');
        if (grantsRefresh) grantsRefresh.addEventListener('click', () => loadGrants());
        const grantsActive = document.getElementById('grants-active-only');
        if (grantsActive) grantsActive.addEventListener('change', () => loadGrants());

        await loadSection('overview');
    });
})();

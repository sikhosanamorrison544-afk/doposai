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
        const hasAdmins = parseAdminUsernames(r.admin_usernames).length > 0;
        const resetBtn = hasAdmins
            ? '<button type="button" class="row-action-btn row-action-btn--muted js-reset-pw" data-tenant-id="' +
              escapeHtml(String(r.id)) + '">Reset password</button>'
            : '<button type="button" class="row-action-btn" disabled title="No admin login">Reset password</button>';
        return (
            '<div class="row-actions-stack">' +
            '<button type="button" class="row-action-btn js-grant-sub" data-tenant-id="' +
            escapeHtml(String(r.id)) + '">Grant subscription</button>' +
            '<button type="button" class="row-action-btn row-action-btn--danger js-revoke-sub" data-tenant-id="' +
            escapeHtml(String(r.id)) + '">Revoke access</button>' +
            resetBtn +
            '</div>'
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
        const isTrial = m.mode.value === 'trial';
        m.daysLabel.textContent = isTrial ? 'Trial length (days)' : 'Duration (days)';
        m.days.max = isTrial ? '365' : '3650';
        m.days.value = isTrial ? '14' : m.cycle && m.cycle.value === 'yearly' ? '365' : '30';
        if (m.cycle) m.cycle.disabled = isTrial;
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
        const body = {
            plan: m.plan ? m.plan.value : 'pro',
            billing_cycle: m.cycle ? m.cycle.value : 'monthly',
            grant_mode: m.mode ? m.mode.value : 'active',
            trial_days: m.days ? parseInt(m.days.value, 10) || 14 : 14,
            duration_days: m.days ? parseInt(m.days.value, 10) || 30 : 30,
            note: m.note && m.note.value.trim() ? m.note.value.trim() : null,
        };
        if (m.confirmBtn) m.confirmBtn.disabled = true;
        setGrantModalMessage('Saving…', '');
        try {
            await platformFetchJson('/api/platform/tenants/' + tenantId + '/subscription/grant', {
                method: 'POST',
                body: body,
            });
            setGrantModalMessage('Subscription updated.', 'success');
            closeGrantModal();
            await loadTenants();
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

    function wireTenantActionButtons(body) {
        body.querySelectorAll('button.js-grant-sub').forEach((btn) => {
            btn.addEventListener('click', () => {
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (!row) return;
                const m = getGrantModal();
                if (m.backdrop) m.backdrop.dataset.tenantId = id;
                openGrantModal(row);
            });
        });
        body.querySelectorAll('button.js-revoke-sub').forEach((btn) => {
            btn.addEventListener('click', () => {
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (row) revokeSubscription(row);
            });
        });
        body.querySelectorAll('button.js-reset-pw').forEach((btn) => {
            btn.addEventListener('click', () => {
                const id = btn.getAttribute('data-tenant-id');
                const row = _tenantsById.get(id);
                if (row) openResetModal(row);
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

    function updateStats(rows) {
        const statsEl = document.getElementById('platform-stats');
        const totalEl = document.getElementById('stat-total');
        const activeEl = document.getElementById('stat-active');
        const usersEl = document.getElementById('stat-users');
        if (!statsEl || !totalEl) return;

        if (!Array.isArray(rows) || rows.length === 0) {
            statsEl.style.display = 'none';
            return;
        }

        const activeCount = rows.filter((r) => r.is_active).length;
        const userTotal = rows.reduce((sum, r) => sum + (Number(r.user_count) || 0), 0);

        totalEl.textContent = String(rows.length);
        if (activeEl) activeEl.textContent = String(activeCount);
        if (usersEl) usersEl.textContent = String(userTotal);
        statsEl.style.display = 'grid';
    }

    // Most recent /api/platform/tenants response, keyed by tenant id, so the
    // per-row "Reset password" handler can look up the tenant without
    // re-parsing the DOM (and without trusting attributes for sensitive data).
    const _tenantsById = new Map();

    async function loadTenants() {
        const errEl = document.getElementById('platform-error');
        const loadingEl = document.getElementById('platform-loading');
        const tableWrap = document.getElementById('platform-table-container');
        const body = document.getElementById('platform-tenants-body');
        const refreshBtn = document.getElementById('platform-refresh-btn');

        errEl.style.display = 'none';
        loadingEl.style.display = 'flex';
        tableWrap.style.display = 'none';
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const rows = await platformFetchJson('/api/platform/tenants');
            loadingEl.style.display = 'none';
            _tenantsById.clear();
            updateStats(rows);

            if (!Array.isArray(rows) || rows.length === 0) {
                body.innerHTML =
                    '<tr><td colspan="9">' +
                    '<div class="platform-empty">' +
                    '<strong>No businesses registered yet</strong>' +
                    'When a store signs up on this platform, it will appear here.' +
                    '</div></td></tr>';
                tableWrap.style.display = 'block';
                return;
            }

            rows.forEach((r) => _tenantsById.set(String(r.id), r));
            body.innerHTML = rows
                .map((r) => {
                    const contact = [r.email, r.phone].filter(Boolean).join(' · ') || '—';
                    return (
                        '<tr>' +
                        '<td class="col-business">' + renderBusinessCell(r) + '</td>' +
                        '<td class="col-owner">' + (escapeHtml(r.owner_name) || '—') + '</td>' +
                        '<td class="col-contact">' + escapeHtml(contact) + '</td>' +
                        '<td>' + renderStatusCell(r) + '</td>' +
                        '<td class="col-plan">' + renderPlanCell(r) + '</td>' +
                        '<td class="col-date">' + renderEndsCell(r) + '</td>' +
                        '<td class="col-num">' + escapeHtml(String(r.user_count)) + '</td>' +
                        '<td class="col-admins">' + escapeHtml(r.admin_usernames) + '</td>' +
                        '<td class="col-actions">' + renderActionsCell(r) + '</td>' +
                        '</tr>'
                    );
                })
                .join('');
            tableWrap.style.display = 'block';

            wireTenantActionButtons(body);
        } catch (e) {
            loadingEl.style.display = 'none';
            updateStats([]);
            if (e && e.message === 'Unauthorized') return;
            errEl.textContent =
                e.message ||
                'Could not load businesses. If you are the platform owner, set PLATFORM_OWNER_EMAILS on the server to include your account email.';
            errEl.style.display = 'block';
        } finally {
            if (refreshBtn) refreshBtn.disabled = false;
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

        const refreshBtn = document.getElementById('platform-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => loadTenants());
        }

        await loadTenants();
    });
})();

function escapeHtml(s) {
    if (s == null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function ensureAdmin() {
    const token = localStorage.getItem('pos_token');
    const userStr = localStorage.getItem('pos_user');
    if (!token || !userStr) {
        window.location.href = '/';
        return false;
    }
    let user;
    try {
        user = JSON.parse(userStr);
    } catch (e) {
        window.location.href = '/';
        return false;
    }
    if (user.role !== 'admin') {
        window.location.href = '/';
        return false;
    }
    const el = document.getElementById('platform-user-info');
    if (el) el.textContent = `${user.username} (${user.role})`;
    return true;
}

async function platformFetchJson(url) {
    const token = localStorage.getItem('pos_token');
    const headers = { Accept: 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(url, { headers });
    const text = await res.text();
    if (res.status === 401) {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.replace('/');
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

function formatDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString();
    } catch (_) {
        return iso;
    }
}

async function loadTenants() {
    const errEl = document.getElementById('platform-error');
    const loadingEl = document.getElementById('platform-loading');
    const tableWrap = document.getElementById('platform-table-container');
    const body = document.getElementById('platform-tenants-body');

    errEl.style.display = 'none';
    loadingEl.style.display = 'block';
    tableWrap.style.display = 'none';

    try {
        const rows = await platformFetchJson('/api/platform/tenants');
        loadingEl.style.display = 'none';
        if (!Array.isArray(rows) || rows.length === 0) {
            body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;">No registered businesses yet.</td></tr>';
            tableWrap.style.display = 'block';
            return;
        }
        body.innerHTML = rows
            .map((r) => {
                const contact = [r.email, r.phone].filter(Boolean).join(' · ') || '—';
                const storeLine = r.store_display_name && r.store_display_name !== r.business_name
                    ? `${escapeHtml(r.business_name)} <span style="opacity:0.7">(${escapeHtml(r.store_display_name)})</span>`
                    : escapeHtml(r.business_name);
                const active = r.is_active ? 'Active' : 'Inactive';
                return `<tr>
                    <td>${storeLine}</td>
                    <td>${escapeHtml(r.owner_name) || '—'}</td>
                    <td>${escapeHtml(contact)}</td>
                    <td>${escapeHtml(r.subscription_status)} (${active})</td>
                    <td>${formatDate(r.trial_ends_at)}</td>
                    <td>${r.user_count}</td>
                    <td style="max-width:220px;word-break:break-word;">${escapeHtml(r.admin_usernames)}</td>
                </tr>`;
            })
            .join('');
        tableWrap.style.display = 'block';
    } catch (e) {
        loadingEl.style.display = 'none';
        errEl.textContent =
            e.message ||
            'Could not load businesses. If you are the platform owner, set PLATFORM_OWNER_USERNAMES on the server to include your admin username.';
        errEl.style.display = 'block';
    }
}

window.addEventListener('load', () => {
    if (!ensureAdmin()) return;
    loadTenants();
});

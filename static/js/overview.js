/**
 * Business Overview Dashboard — single summary API, SVG/CSS charts (no extra libs).
 */
(function () {
    'use strict';

    const token = localStorage.getItem('pos_token');
    if (!token) {
        window.location.replace('/?next=' + encodeURIComponent('/overview'));
        return;
    }

    let lastPayload = null;
    let currencyCode = 'USD';

    function $(id) {
        return document.getElementById(id);
    }

    function pad2(n) {
        return String(n).padStart(2, '0');
    }

    /** Local calendar YYYY-MM-DD (avoid UTC day-shift from toISOString). */
    function localDateISO(d) {
        return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }

    function todayISO() {
        return localDateISO(new Date());
    }

    function daysAgoISO(n) {
        const d = new Date();
        d.setDate(d.getDate() - n);
        return localDateISO(d);
    }

    function money(n) {
        const v = Number(n) || 0;
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency',
                currency: currencyCode || 'USD',
            }).format(v);
        } catch (_) {
            return (
                '$' +
                v.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                })
            );
        }
    }

    function fmtNum(n) {
        return (Number(n) || 0).toLocaleString();
    }

    async function api(path) {
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        const timeoutId = controller
            ? setTimeout(function () { try { controller.abort(); } catch (_) {} }, 15000)
            : null;
        let res;
        try {
            res = await fetch(path, {
                headers: { Authorization: 'Bearer ' + token },
                signal: controller ? controller.signal : undefined,
            });
        } finally {
            if (timeoutId) clearTimeout(timeoutId);
        }
        if (res.status === 401) {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.replace('/');
            throw new Error('Session expired');
        }
        if (res.status === 403) {
            throw new Error('You do not have permission to view this dashboard.');
        }
        if (!res.ok) {
            let detail = 'Request failed';
            try {
                const j = await res.json();
                detail = j.detail || detail;
            } catch (_) {}
            throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
        }
        return res.json();
    }

    function setVisible(el, on) {
        if (!el) return;
        el.hidden = !on;
    }

    function renderCards(cards) {
        const root = $('ov-cards');
        if (!root) return;
        root.innerHTML = '';
        (cards || []).forEach(function (c) {
            const el = document.createElement(c.href ? 'a' : 'div');
            if (c.href) el.href = c.href;
            el.className = 'ov-card';
            if (c.key) el.setAttribute('data-card-key', c.key);
            if (c.key === 'cash_on_hand') el.id = 'ov-card-cash-on-hand';
            let val;
            if (c.available === false) {
                val = c.display || 'Unavailable';
            } else if (c.money === false) {
                val = fmtNum(c.value);
            } else {
                val = money(c.value == null ? 0 : c.value);
            }
            let extra = '';
            if (c.subtitle) {
                extra += '<div class="delta subtitle"></div>';
            }
            if (c.change_pct != null) {
                const sign = c.change_pct > 0 ? '+' : '';
                extra +=
                    '<div class="delta ' +
                    (c.direction || 'neutral') +
                    '">' +
                    sign +
                    c.change_pct.toFixed(1) +
                    '% vs prior period</div>';
            } else if (!c.subtitle && c.direction === 'up') {
                extra += '<div class="delta up">New activity</div>';
            }
            el.innerHTML =
                '<div class="label"></div><div class="value"></div>' + extra;
            el.querySelector('.label').textContent = c.label;
            el.querySelector('.value').textContent = val;
            const sub = el.querySelector('.delta.subtitle');
            if (sub && c.subtitle) sub.textContent = c.subtitle;
            root.appendChild(el);
        });
    }

    function renderTrend(rows) {
        const box = $('ov-chart-trend');
        if (!box) return;
        if (!rows || !rows.length) {
            box.innerHTML =
                '<div class="chart-empty">No sales in this period yet. Try another date range or open POS to record a sale.</div>';
            return;
        }
        const w = 400;
        const h = 160;
        const pad = 24;
        const max = Math.max.apply(
            null,
            rows.map(function (r) {
                return r.revenue;
            }).concat([1])
        );
        const pts = rows
            .map(function (r, i) {
                const x = pad + (i * (w - pad * 2)) / Math.max(rows.length - 1, 1);
                const y = h - pad - (r.revenue / max) * (h - pad * 2);
                return x + ',' + y;
            })
            .join(' ');
        box.innerHTML =
            '<svg class="trend-svg" viewBox="0 0 ' +
            w +
            ' ' +
            h +
            '" preserveAspectRatio="none" role="img">' +
            '<polyline fill="none" stroke="#667eea" stroke-width="2.5" points="' +
            pts +
            '" />' +
            '</svg>' +
            '<div class="chart-caption">' +
            rows.length +
            ' point(s) · peak ' +
            money(max) +
            '</div>';
    }

    function renderBars(boxId, items, labelKey, valueKey) {
        const box = $(boxId);
        if (!box) return;
        if (!items || !items.length) {
            box.innerHTML =
                '<div class="chart-empty">No data for this period. Charts appear after completed sales are recorded.</div>';
            return;
        }
        const max = Math.max.apply(
            null,
            items.map(function (i) {
                return Number(i[valueKey]) || 0;
            }).concat([1])
        );
        box.innerHTML = items
            .map(function (i) {
                const v = Number(i[valueKey]) || 0;
                const pct = Math.round((v / max) * 100);
                const label = String(i[labelKey] || '').replace(/</g, '&lt;');
                return (
                    '<div class="bar-row"><span>' +
                    label +
                    '</span><div class="bar-track"><div class="bar-fill" style="width:' +
                    pct +
                    '%"></div></div><span>' +
                    money(v) +
                    '</span></div>'
                );
            })
            .join('');
    }

    function renderInventory(items) {
        const box = $('ov-chart-inventory');
        if (!box) return;
        if (!items || !items.length) {
            box.innerHTML =
                '<div class="chart-empty">No active products yet. Add stock from Inventory.</div>';
            return;
        }
        const total =
            items.reduce(function (s, i) {
                return s + (Number(i.count) || 0);
            }, 0) || 1;
        box.innerHTML = items
            .map(function (i) {
                const c = Number(i.count) || 0;
                const pct = Math.round((c / total) * 100);
                return (
                    '<div class="bar-row"><span>' +
                    String(i.label).replace(/</g, '&lt;') +
                    '</span><div class="bar-track"><div class="bar-fill" style="width:' +
                    pct +
                    '%"></div></div><span>' +
                    fmtNum(c) +
                    '</span></div>'
                );
            })
            .join('');
    }

    function renderAlerts(alerts) {
        const root = $('ov-alerts');
        if (!root) return;
        if (!alerts || !alerts.length) {
            setVisible(root, false);
            root.innerHTML = '';
            return;
        }
        setVisible(root, true);
        root.innerHTML = alerts
            .map(function (a) {
                const sev = a.severity === 'high' ? 'high' : '';
                const href = a.href || '#';
                return (
                    '<a class="ov-alert ' +
                    sev +
                    '" href="' +
                    href +
                    '">' +
                    String(a.message || '').replace(/</g, '&lt;') +
                    '</a>'
                );
            })
            .join('');
    }

    function renderActivity(rows) {
        const root = $('ov-activity');
        if (!root) return;
        if (!rows || !rows.length) {
            root.innerHTML = '<div class="chart-empty">No recent sales</div>';
            return;
        }
        root.innerHTML =
            '<table><thead><tr><th>When</th><th>Reference</th><th>Cashier</th><th>Amount</th><th>Status</th></tr></thead><tbody>' +
            rows
                .map(function (r) {
                    const when = r.at ? new Date(r.at).toLocaleString() : '—';
                    return (
                        '<tr><td>' +
                        when +
                        '</td><td>' +
                        String(r.reference || '').replace(/</g, '&lt;') +
                        '</td><td>' +
                        String(r.user || '').replace(/</g, '&lt;') +
                        '</td><td>' +
                        money(r.amount) +
                        '</td><td>' +
                        String(r.status || '').replace(/</g, '&lt;') +
                        '</td></tr>'
                    );
                })
                .join('') +
            '</tbody></table>';
    }

    function fillBranches(data) {
        const wrap = $('ov-branch-wrap');
        const sel = $('ov-branch');
        if (!wrap || !sel) return;
        const can = data.branches && data.branches.can_select;
        const opts = (data.branches && data.branches.options) || [];
        if (!can || !opts.length) {
            wrap.style.display = 'none';
            return;
        }
        wrap.style.display = '';
        const cur = data.branches.selected_id;
        sel.innerHTML =
            '<option value="">All branches</option>' +
            opts
                .map(function (b) {
                    return (
                        '<option value="' +
                        b.id +
                        '"' +
                        (cur === b.id ? ' selected' : '') +
                        '>' +
                        String(b.name).replace(/</g, '&lt;') +
                        '</option>'
                    );
                })
                .join('');
    }

    async function loadDashboard() {
        setVisible($('ov-loading'), true);
        setVisible($('ov-error'), false);
        setVisible($('ov-empty'), false);

        const from = $('ov-from').value || todayISO();
        const to = $('ov-to').value || todayISO();
        const branch = $('ov-branch') ? $('ov-branch').value : '';
        let q =
            '/api/overview/summary?from_date=' +
            encodeURIComponent(from) +
            '&to_date=' +
            encodeURIComponent(to);
        if (branch) q += '&branch_id=' + encodeURIComponent(branch);

        try {
            const data = await api(q);
            lastPayload = data;
            currencyCode = (data.business && data.business.currency) || 'USD';
            setVisible($('ov-loading'), false);

            $('ov-business-name').textContent =
                (data.business && data.business.name) || 'Business';
            const branchName =
                (data.business && data.business.branch_name) || 'All branches';
            $('ov-branch-line').textContent =
                branchName +
                ' · ' +
                from +
                ' → ' +
                to +
                ' · ' +
                new Date().toLocaleDateString();

            fillBranches(data);
            renderCards(data.cards || []);
            renderTrend(data.sales_trend || []);
            renderBars('ov-chart-payments', data.payment_methods || [], 'method', 'amount');
            renderBars('ov-chart-products', data.top_products || [], 'name', 'revenue');
            renderInventory(data.inventory_status || []);
            renderAlerts(data.alerts || []);
            renderActivity(data.recent_activity || []);

            const updated = data.meta && data.meta.generated_at;
            $('ov-updated').textContent = updated
                ? 'Updated ' + new Date(updated).toLocaleString()
                : '';

            const noSales = !(data.summary && data.summary.completed_sales);
            setVisible($('ov-empty'), noSales);
        } catch (e) {
            setVisible($('ov-loading'), false);
            setVisible($('ov-error'), true);
            $('ov-error-text').textContent = e.message || 'Could not load dashboard.';
        }
    }

    function initDates() {
        // Default headline period: today; presets can widen
        $('ov-from').value = todayISO();
        $('ov-to').value = todayISO();
    }

    let meUser = null;

    function hasPerm(name) {
        return !!(meUser && Array.isArray(meUser.permissions) && meUser.permissions.indexOf(name) !== -1);
    }

    function applyOverviewGates() {
        const canSell = meUser && (meUser.can_access_pos === true || hasPerm('sales'));
        const openPos = $('ov-open-pos');
        const emptyPos = $('ov-empty-pos');
        if (openPos) openPos.hidden = !canSell;
        if (emptyPos) emptyPos.hidden = !canSell;

        document.querySelectorAll('#ov-quick-actions .overview-quick-action').forEach(function (el) {
            const need = el.getAttribute('data-perm');
            let show = true;
            if (need === 'admin') show = hasPerm('manage_settings') || hasPerm('manage_users');
            else if (need === 'inventory') show = hasPerm('manage_inventory');
            else if (need === 'transfers') show = hasPerm('branch.transfer.view');
            else if (need === 'pending') show = hasPerm('manage_pending_collection');
            else if (need === 'refunds') show = hasPerm('view_refunds') || hasPerm('request_refunds');
            else if (need === 'layby') show = hasPerm('sales') || hasPerm('manage_settings');
            else if (need === 'reports') show = hasPerm('view_reports');
            else if (need === 'withdrawals') show = hasPerm('view_withdrawals') || hasPerm('process_withdrawals');
            el.style.display = show ? '' : 'none';
        });
    }

    async function refreshPendingBadge() {
        const badge = $('ov-pending-badge');
        if (!badge || !hasPerm('manage_pending_collection')) return;
        try {
            const rows = await api('/api/sales/pending-collection');
            const n = Array.isArray(rows) ? rows.length : 0;
            badge.textContent = String(n);
            badge.hidden = n <= 0;
        } catch (_) {
            badge.hidden = true;
        }
    }

    async function refreshNotifBadge() {
        const badge = $('ov-notif-badge');
        if (!badge) return;
        try {
            const data = await api('/api/notifications/unread-count');
            const n = Number(data.count) || 0;
            badge.textContent = String(n);
            badge.hidden = n <= 0;
        } catch (_) {
            badge.hidden = true;
        }
    }

    async function openNotifications() {
        const panel = $('ov-notifications-panel');
        const list = $('ov-notif-list');
        if (!panel || !list) return;
        panel.hidden = false;
        list.textContent = 'Loading…';
        try {
            const rows = await api('/api/notifications');
            if (!rows || !rows.length) {
                list.textContent = 'No notifications.';
                return;
            }
            list.innerHTML = '';
            rows.slice(0, 40).forEach(function (n) {
                const div = document.createElement('div');
                div.className = 'overview-notif-item';
                div.textContent = n.title || n.message || n.body || JSON.stringify(n);
                list.appendChild(div);
            });
            await refreshNotifBadge();
        } catch (e) {
            list.textContent = e.message || 'Could not load notifications.';
        }
    }

    function cycleTheme() {
        const order = ['default', 'light', 'classic'];
        let cur = 'classic';
        try {
            cur = localStorage.getItem('pos-theme') || 'classic';
        } catch (_) {}
        const idx = order.indexOf(cur);
        const next = order[(idx + 1) % order.length];
        if (typeof window.posApplyTheme === 'function') {
            window.posApplyTheme(next);
        } else {
            try {
                localStorage.setItem('pos-theme', next);
            } catch (_) {}
            document.body.classList.remove('theme-default', 'theme-light', 'theme-classic');
            document.documentElement.classList.remove(
                'theme-default',
                'theme-light',
                'theme-classic'
            );
            document.body.classList.add('theme-' + next);
            document.documentElement.classList.add('theme-' + next);
        }
    }

    function setFabOpen(open) {
        const menu = $('ov-fab-menu');
        const toggle = $('ov-fab-toggle');
        if (!menu || !toggle) return;
        menu.hidden = !open;
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        toggle.setAttribute('aria-label', open ? 'Close tools menu' : 'Open tools menu');
        toggle.textContent = open ? '×' : '+';
    }

    function initFab() {
        const toggle = $('ov-fab-toggle');
        const menu = $('ov-fab-menu');
        if (!toggle || !menu) return;
        function onToggle(e) {
            if (e) e.preventDefault();
            setFabOpen(menu.hidden);
        }
        toggle.addEventListener('click', onToggle);
        toggle.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setFabOpen(menu.hidden);
            }
        });
        document.addEventListener('click', function (e) {
            const root = document.querySelector('.overview-fab-root');
            if (!root || root.contains(e.target)) return;
            setFabOpen(false);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                setFabOpen(false);
                const panel = $('ov-notifications-panel');
                if (panel) panel.hidden = true;
            }
        });
        const notifBtn = $('ov-fab-notifications');
        if (notifBtn) {
            notifBtn.addEventListener('click', function () {
                setFabOpen(false);
                openNotifications();
            });
        }
        const themeBtn = $('ov-fab-theme');
        if (themeBtn) {
            themeBtn.addEventListener('click', function () {
                cycleTheme();
            });
        }
        const closeNotif = $('ov-notif-close');
        if (closeNotif) {
            closeNotif.addEventListener('click', function () {
                const panel = $('ov-notifications-panel');
                if (panel) panel.hidden = true;
            });
        }
    }

    async function gateAccess() {
        try {
            meUser = await api('/api/auth/me');
            if (!(meUser.permissions || []).includes('view_reports')) {
                window.location.replace(
                    meUser.can_access_pos ? '/?pos=1' : '/'
                );
                return false;
            }
            applyOverviewGates();
            return true;
        } catch (_) {
            window.location.replace('/');
            return false;
        }
    }

    document.addEventListener('DOMContentLoaded', async function () {
        initDates();
        const ok = await gateAccess();
        if (!ok) return;

        initFab();
        refreshPendingBadge();
        refreshNotifBadge();
        setInterval(refreshNotifBadge, 60000);

        $('ov-refresh').addEventListener('click', loadDashboard);
        $('ov-retry').addEventListener('click', loadDashboard);
        $('ov-from').addEventListener('change', loadDashboard);
        $('ov-to').addEventListener('change', loadDashboard);
        if ($('ov-branch')) $('ov-branch').addEventListener('change', loadDashboard);

        document.querySelectorAll('[data-preset]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const p = btn.getAttribute('data-preset');
                document.querySelectorAll('[data-preset]').forEach(function (b) {
                    b.classList.toggle('is-active', b === btn);
                });
                if (p === 'today') {
                    $('ov-from').value = todayISO();
                    $('ov-to').value = todayISO();
                } else {
                    const n = parseInt(p, 10) || 7;
                    $('ov-from').value = daysAgoISO(n - 1);
                    $('ov-to').value = todayISO();
                }
                loadDashboard();
            });
        });
        const todayBtn = document.querySelector('[data-preset="today"]');
        if (todayBtn) todayBtn.classList.add('is-active');

        $('ov-logout').addEventListener('click', function () {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).finally(function () {
                window.location.href = '/';
            });
        });

        loadDashboard();
    });
})();

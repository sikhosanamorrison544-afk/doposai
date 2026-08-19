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

    function todayISO() {
        const d = new Date();
        return d.toISOString().slice(0, 10);
    }

    function daysAgoISO(n) {
        const d = new Date();
        d.setDate(d.getDate() - n);
        return d.toISOString().slice(0, 10);
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
        const res = await fetch(path, {
            headers: { Authorization: 'Bearer ' + token },
        });
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
            const val = c.money ? money(c.value) : fmtNum(c.value);
            let delta = '';
            if (c.change_pct != null) {
                const sign = c.change_pct > 0 ? '+' : '';
                delta =
                    '<div class="delta ' +
                    (c.direction || 'neutral') +
                    '">' +
                    sign +
                    c.change_pct.toFixed(1) +
                    '% vs prior period</div>';
            } else if (c.direction === 'up') {
                delta = '<div class="delta up">New activity</div>';
            }
            el.innerHTML =
                '<div class="label"></div><div class="value"></div>' + delta;
            el.querySelector('.label').textContent = c.label;
            el.querySelector('.value').textContent = val;
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
            '<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="' +
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

    async function gateAccess() {
        try {
            const me = await api('/api/auth/me');
            if (!(me.permissions || []).includes('view_reports')) {
                window.location.replace('/?pos=1');
                return false;
            }
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

        $('ov-refresh').addEventListener('click', loadDashboard);
        $('ov-retry').addEventListener('click', loadDashboard);
        $('ov-from').addEventListener('change', loadDashboard);
        $('ov-to').addEventListener('change', loadDashboard);
        if ($('ov-branch')) $('ov-branch').addEventListener('change', loadDashboard);

        document.querySelectorAll('[data-preset]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const p = btn.getAttribute('data-preset');
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

        $('ov-logout').addEventListener('click', function () {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
        });

        loadDashboard();
    });
})();

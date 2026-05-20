(function () {
    const state = {
        plans: [],
        selectedPlan: 'starter',
        cycle: 'monthly',
        lastPaymentRef: null,
        lastPollUrl: null,
    };

    function token() {
        return localStorage.getItem('pos_token');
    }

    function showMsg(text, type) {
        const el = document.getElementById('billing-message');
        if (!el) return;
        el.textContent = text || '';
        el.className = 'billing-msg' + (type ? ' ' + type : '');
        el.style.display = text ? 'block' : 'none';
    }

    async function api(path, options) {
        const headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
        const t = token();
        if (t) headers.Authorization = 'Bearer ' + t;
        const res = await fetch(path, { ...options, headers: { ...headers, ...(options && options.headers) } });
        const text = await res.text();
        let data = null;
        try {
            data = text ? JSON.parse(text) : null;
        } catch (e) {
            data = { detail: text };
        }
        if (!res.ok) {
            let detail = res.statusText || 'Request failed';
            if (data && data.detail) {
                detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
            }
            const err = new Error(detail);
            err.status = res.status;
            throw err;
        }
        return data;
    }

    function formatDate(iso) {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleString();
        } catch (e) {
            return iso;
        }
    }

    function renderStatus(sub) {
        const line = document.getElementById('sub-status-line');
        const pill = document.getElementById('sub-status-pill');
        const dates = document.getElementById('sub-dates');
        const banner = document.getElementById('trial-banner');
        const eff = sub.effective_status || sub.status;
        const planDetail = document.getElementById('sub-plan-detail');
        if (planDetail) {
            const c = sub.billing_cycle ? sub.billing_cycle : 'not set yet';
            planDetail.textContent =
                'Current plan: ' +
                (sub.plan ? sub.plan.charAt(0).toUpperCase() + sub.plan.slice(1) : 'Starter') +
                ' · ' +
                c;
        }
        const daysEl = document.getElementById('sub-days-remaining');
        if (daysEl) {
            if (typeof sub.days_remaining === 'number') {
                daysEl.textContent = sub.days_remaining + ' days remaining';
            } else {
                daysEl.textContent = 'No renewal date yet — subscribe to activate.';
            }
        }
        if (line) {
            line.textContent = 'Status: ' + eff.replace(/_/g, ' ') + (sub.access_allowed === false ? ' (access blocked)' : '');
        }
        if (pill) {
            pill.textContent = eff.replace('_', ' ');
            pill.className = 'status-pill status-' + (eff.includes('expired') ? 'expired' : eff === 'active' ? 'active' : eff === 'pending_payment' ? 'pending' : 'trial');
        }
        if (dates) {
            const parts = [];
            if (sub.trial_end) parts.push('Trial ends: ' + formatDate(sub.trial_end));
            if (sub.subscription_end) parts.push('Subscription ends: ' + formatDate(sub.subscription_end));
            dates.textContent = parts.join(' · ');
        }
        if (banner) {
            banner.style.display =
                eff === 'trial' || eff === 'trial_expired' || eff === 'expired' ? 'block' : 'none';
        }
    }

    function renderPlans() {
        const grid = document.getElementById('plan-grid');
        if (!grid) return;
        grid.innerHTML = '';
        state.plans.forEach(function (p) {
            const price = p[state.cycle];
            if (!price) return;
            const card = document.createElement('div');
            card.className = 'plan-card' + (state.selectedPlan === p.id ? ' selected' : '');
            card.innerHTML =
                '<h3>' +
                escapeHtml(p.name) +
                '</h3><div class="price">$' +
                Number(price.amount_usd).toFixed(2) +
                '</div><p style="font-size:13px;color:#64748b">' +
                escapeHtml(price.label) +
                '</p>' +
                (p.highlights && p.highlights.length
                    ? '<ul style="font-size:12px;color:#475569;margin:10px 0 0;padding-left:18px;text-align:left">' +
                      p.highlights
                          .map(function (h) {
                              return '<li>' + escapeHtml(h) + '</li>';
                          })
                          .join('') +
                      '</ul>'
                    : '');
            card.onclick = function () {
                state.selectedPlan = p.id;
                renderPlans();
            };
            grid.appendChild(card);
        });
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    async function loadPlans() {
        const data = await api('/api/subscriptions/plans');
        state.plans = data.plans || [];
        renderPlans();
    }

    async function loadStatus() {
        const sub = await api('/api/subscriptions/status');
        renderStatus(sub);
        if (sub.access_allowed === false) {
            showMsg('Subscription inactive. Pay with EcoCash to restore access.', 'error');
        }
        return sub;
    }

    async function loadHistory() {
        const data = await api('/api/billing/history');
        const tbody = document.getElementById('payments-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        (data.payments || []).forEach(function (p) {
            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td>' +
                escapeHtml(p.payment_reference) +
                '</td><td>' +
                escapeHtml(p.currency) +
                ' ' +
                Number(p.amount).toFixed(2) +
                '</td><td>' +
                escapeHtml(p.status) +
                '</td><td>' +
                formatDate(p.created_at) +
                '</td>';
            tbody.appendChild(tr);
        });
    }

    async function initiatePayment(useEco) {
        const phone = document.getElementById('ecocash-phone').value.trim();
        if (useEco && !phone) {
            showMsg('Enter your EcoCash number (e.g. 0771234567).', 'error');
            return;
        }
        showMsg('Starting payment…', 'info');
        const body = {
            plan: state.selectedPlan,
            billing_cycle: state.cycle,
            channel: useEco ? 'ecocash' : 'web',
        };
        if (useEco) body.ecocash_phone = phone;
        const data = await api('/api/payments/initiate', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        state.lastPaymentRef = data.payment_reference;
        state.lastPollUrl = data.poll_url;
        localStorage.setItem('billing_last_ref', data.payment_reference);
        if (data.poll_url) localStorage.setItem('billing_poll_url', data.poll_url);
        if (data.instructions) {
            const inst = document.getElementById('payment-instructions');
            inst.style.display = 'block';
            inst.textContent = data.instructions;
        }
        if (data.redirect_url) {
            window.open(data.redirect_url, '_blank');
            showMsg('Complete payment in the Paynow window, then click “I’ve paid — verify”.', 'info');
        } else if (data.instructions) {
            showMsg('Check your phone for EcoCash, then verify payment.', 'info');
        } else {
            showMsg('Payment started. Reference: ' + data.payment_reference, 'success');
        }
    }

    async function verifyPayment() {
        const ref =
            state.lastPaymentRef || localStorage.getItem('billing_last_ref');
        if (!ref) {
            showMsg('No pending payment. Start a payment first.', 'error');
            return;
        }
        showMsg('Verifying with Paynow…', 'info');
        const data = await api('/api/payments/verify', {
            method: 'POST',
            body: JSON.stringify({
                payment_reference: ref,
                poll_url: state.lastPollUrl || localStorage.getItem('billing_poll_url'),
            }),
        });
        if (data.paid) {
            showMsg('Payment confirmed. Subscription is active.', 'success');
            localStorage.removeItem('billing_last_ref');
            localStorage.removeItem('billing_poll_url');
            await loadStatus();
            await loadHistory();
        } else {
            showMsg('Payment not confirmed yet. Try again in a minute.', 'info');
        }
    }

    function bindUi() {
        document.getElementById('cycle-monthly').onclick = function () {
            state.cycle = 'monthly';
            document.getElementById('cycle-monthly').classList.add('active');
            document.getElementById('cycle-yearly').classList.remove('active');
            renderPlans();
        };
        document.getElementById('cycle-yearly').onclick = function () {
            state.cycle = 'yearly';
            document.getElementById('cycle-yearly').classList.add('active');
            document.getElementById('cycle-monthly').classList.remove('active');
            renderPlans();
        };
        document.getElementById('btn-pay-ecocash').onclick = function () {
            initiatePayment(true).catch(function (e) {
                showMsg(e.message, 'error');
            });
        };
        document.getElementById('btn-pay-web').onclick = function () {
            initiatePayment(false).catch(function (e) {
                showMsg(e.message, 'error');
            });
        };
        document.getElementById('btn-verify-payment').onclick = function () {
            verifyPayment().catch(function (e) {
                showMsg(e.message, 'error');
            });
        };
    }

    async function init() {
        const t = token();
        const userStr = localStorage.getItem('pos_user');
        if (!t || !userStr) {
            document.getElementById('billing-gate').style.display = 'block';
            return;
        }
        try {
            const user = JSON.parse(userStr);
            if (user.role !== 'admin') {
                document.getElementById('billing-gate').style.display = 'block';
                document.querySelector('#billing-gate p').textContent =
                    'Only business admins can manage billing.';
                return;
            }
        } catch (e) {
            document.getElementById('billing-gate').style.display = 'block';
            return;
        }
        document.getElementById('billing-app').style.display = 'block';
        bindUi();
        try {
            await loadPlans();
            await loadStatus();
            await loadHistory();
        } catch (e) {
            showMsg(e.message || 'Failed to load billing', 'error');
        }
        const params = new URLSearchParams(window.location.search);
        if (params.get('payment') === 'return') {
            verifyPayment().catch(function () {});
        }
    }

    document.addEventListener('DOMContentLoaded', init);
})();

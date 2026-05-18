/**
 * Android WebView UI for withdrawals, analytics, and pending collection.
 */
(function () {
    'use strict';

    function escapeHtml(text) {
        if (text == null || text === '') return '';
        const d = document.createElement('div');
        d.textContent = String(text);
        return d.innerHTML;
    }

    function reasonBadgeClass(reason) {
        if (reason === 'Daily expenses') return 'expense';
        if (reason === 'Buying company assets') return 'assets';
        return 'other';
    }

    function renderWithdrawalsMobile(withdrawals) {
        const list = document.getElementById('withdrawals-mobile-list');
        if (!list || !window.isPosAndroidApp || !window.isPosAndroidApp()) return;

        const recent = (withdrawals || []).slice(0, 20);
        if (recent.length === 0) {
            list.innerHTML = '<div class="pa-empty-state">No withdrawals match your filters.</div>';
            return;
        }

        list.innerHTML =
            '<p class="pa-list-label">Recent withdrawals</p>' +
            recent
                .map(function (w) {
                    const date = new Date(w.created_at);
                    const dateStr =
                        date.toLocaleDateString() +
                        ' · ' +
                        date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    const amount = parseFloat(w.amount || 0).toFixed(2);
                    const reason = w.reason || 'Other';
                    const badge = reasonBadgeClass(reason);
                    return (
                        '<article class="withdrawal-mobile-card">' +
                        '<div class="card-top">' +
                        '<div><span class="reason-badge ' +
                        badge +
                        '">' +
                        escapeHtml(reason) +
                        '</span></div>' +
                        '<div class="amount">$' +
                        amount +
                        '</div></div>' +
                        '<div class="meta">' +
                        escapeHtml(dateStr) +
                        '<br>Receipt <strong>' +
                        escapeHtml(w.receipt_number || 'N/A') +
                        '</strong> · ' +
                        escapeHtml(w.cashier_name || 'Unknown') +
                        '</div>' +
                        (w.notes
                            ? '<div class="notes">' + escapeHtml(w.notes) + '</div>'
                            : '') +
                        '</article>'
                    );
                })
                .join('');
    }

    window.renderWithdrawalsMobile = renderWithdrawalsMobile;

    function formatUSD(amount) {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
            Number(amount) || 0,
        );
    }

    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function renderPendingCollectionMobile(sales, container) {
        if (!container) return;
        if (!sales || sales.length === 0) {
            container.innerHTML =
                '<div class="pa-empty-state">No items pending collection. Paid orders waiting for pickup will appear here.</div>';
            return;
        }

        container.innerHTML = sales
            .map(function (sale) {
                const itemsHtml = (sale.items || [])
                    .map(function (item) {
                        return (
                            '<div class="pending-item-row">' +
                            '<span class="item-name">' +
                            escapeHtml(item.product_name) +
                            '</span>' +
                            '<span class="item-qty">×' +
                            escapeHtml(item.quantity) +
                            '</span>' +
                            '<span class="item-total">' +
                            formatUSD(item.line_total) +
                            '</span></div>'
                        );
                    })
                    .join('');

                return (
                    '<article class="pending-sale-card">' +
                    '<header class="card-header">' +
                    '<div><h3 class="sale-id">Sale #' +
                    escapeHtml(sale.id) +
                    '</h3><p class="sale-date">' +
                    escapeHtml(formatDate(sale.created_at)) +
                    '</p></div>' +
                    '<div class="sale-total">' +
                    formatUSD(sale.total) +
                    '</div></header>' +
                    '<div class="card-body">' +
                    '<div class="info-row"><span>Customer</span><strong>' +
                    escapeHtml(sale.customer_name || 'Walk-in') +
                    '</strong></div>' +
                    '<div class="info-row"><span>Cashier</span><strong>' +
                    escapeHtml(sale.cashier_name || '—') +
                    '</strong></div>' +
                    '<p class="items-title">Items to collect</p>' +
                    itemsHtml +
                    '</div>' +
                    '<footer class="card-footer">' +
                    '<button type="button" class="btn-collect" onclick="markAsCollected(' +
                    sale.id +
                    ')">Mark as collected</button>' +
                    '</footer></article>'
                );
            })
            .join('');
    }

    window.renderPendingCollectionMobile = renderPendingCollectionMobile;

    function wrapWithdrawalsLayout() {
        const grid = document.querySelector(
            'body.page-withdrawals section > div[style*="grid-template-columns"]',
        );
        if (grid) grid.classList.add('pa-stat-grid');
        const filters = document.querySelector(
            'body.page-withdrawals section > div[style*="rgba(17, 24, 39, 0.3)"]',
        );
        if (filters) filters.classList.add('pa-filters');
    }

    function initWithdrawalsPageUi() {
        if (!window.isPosAndroidApp || !window.isPosAndroidApp()) return;
        wrapWithdrawalsLayout();
        if (typeof window.wireWebVersionButton === 'function') {
            window.wireWebVersionButton('btn-view-withdrawals-web', '/withdrawals/history');
        }
    }

    function initAnalyticsPageUi() {
        if (!window.isPosAndroidApp || !window.isPosAndroidApp()) return;
        if (typeof window.wireWebVersionButton === 'function') {
            window.wireWebVersionButton('btn-view-analytics-revenue-web', '/analytics');
        }
    }

    function initPendingCollectionPageUi() {
        if (!window.isPosAndroidApp || !window.isPosAndroidApp()) return;
        const refreshBtn = document.getElementById('btn-refresh-android');
        if (refreshBtn && typeof window.loadPendingCollection === 'function') {
            refreshBtn.addEventListener('click', function () {
                window.loadPendingCollection();
            });
        }
    }

    function initPosAndroidPageUi() {
        if (!document.body) return;
        if (document.body.classList.contains('page-withdrawals')) initWithdrawalsPageUi();
        if (document.body.classList.contains('page-analytics')) initAnalyticsPageUi();
        if (document.body.classList.contains('page-pending-collection')) initPendingCollectionPageUi();
    }

    window.initWithdrawalsPageUi = initWithdrawalsPageUi;
    window.initAnalyticsPageUi = initAnalyticsPageUi;
    window.initPendingCollectionPageUi = initPendingCollectionPageUi;
    window.initPosAndroidPageUi = initPosAndroidPageUi;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPosAndroidPageUi);
    } else {
        initPosAndroidPageUi();
    }
})();

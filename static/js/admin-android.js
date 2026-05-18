/**
 * Admin page layout for POS Android WebView (body.pos-android-app).
 */
(function () {
    'use strict';

    function isPosAndroidApp() {
        try {
            if (localStorage.getItem('pos_android_app') === '1') return true;
        } catch (e) { /* ignore */ }
        return document.body && document.body.classList.contains('pos-android-app');
    }

    function clickEl(id) {
        const el = document.getElementById(id);
        if (el) el.click();
    }

    function navigate(path) {
        window.location.href = path;
    }

    function syncMobileHeader() {
        const shop = document.querySelector('.shop-name');
        const user = document.getElementById('admin-user-info');
        const shopEl = document.getElementById('admin-mobile-shop');
        const userEl = document.getElementById('admin-mobile-user');
        if (shopEl && shop) shopEl.textContent = shop.textContent.trim();
        if (userEl && user) userEl.textContent = user.textContent.trim();
    }

    function wireMobileToolbar() {
        const addMobile = document.getElementById('btn-show-product-form-mobile');
        const importMobile = document.getElementById('btn-import-inventory-mobile');
        if (addMobile) {
            addMobile.addEventListener('click', function (e) {
                e.preventDefault();
                clickEl('btn-show-product-form');
            });
        }
        if (importMobile) {
            importMobile.addEventListener('click', function (e) {
                e.preventDefault();
                clickEl('btn-import-inventory');
            });
        }
    }

    function wireMobileActions() {
        const actions = [
            { id: 'admin-action-settings', fn: function () { navigate('/store-settings'); } },
            { id: 'admin-action-report', fn: function () { clickEl('btn-toggle-report'); } },
            { id: 'admin-action-withdrawals', fn: function () { navigate('/withdrawals/history'); } },
            { id: 'admin-action-analytics', fn: function () { navigate('/analytics'); } },
            { id: 'admin-action-shifts', fn: function () { clickEl('btn-toggle-shifts'); } },
            { id: 'admin-action-pending', fn: function () { navigate('/pending-collection'); } },
            { id: 'admin-action-billing', fn: function () { navigate('/billing'); } },
        ];
        actions.forEach(function (a) {
            const btn = document.getElementById(a.id);
            if (btn) {
                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    a.fn();
                });
            }
        });
    }

    function setupProductSearch() {
        const input = document.getElementById('admin-product-search');
        if (!input) return;
        input.addEventListener('input', function () {
            filterMobileProducts(input.value.trim().toLowerCase());
        });
    }

    function filterMobileProducts(query) {
        const list = document.getElementById('products-mobile-list');
        if (!list) return;
        const cards = list.querySelectorAll('.admin-product-card');
        cards.forEach(function (card) {
            const hay = (card.getAttribute('data-search') || '').toLowerCase();
            card.style.display = !query || hay.indexOf(query) >= 0 ? '' : 'none';
        });
    }

    function renderAdminProductsMobile(products) {
        const list = document.getElementById('products-mobile-list');
        if (!list || !isPosAndroidApp()) return;

        list.innerHTML = '';
        if (!products || products.length === 0) {
            list.innerHTML = '<div class="admin-mobile-empty">No products yet. Tap Add Product or Import.</div>';
            return;
        }

        products.forEach(function (p) {
            const card = document.createElement('article');
            card.className = 'admin-product-card';
            if (Number(p.stock_qty) <= 5) card.classList.add('low-stock');

            const searchText = [p.name, p.barcode, p.id].filter(Boolean).join(' ');
            card.setAttribute('data-search', searchText);

            card.innerHTML =
                '<div class="name"></div>' +
                '<div class="meta">' +
                '<div><strong>Stock</strong> <span class="stock"></span></div>' +
                '<div><strong>Price</strong> $<span class="price"></span></div>' +
                '<div><strong>Cost</strong> $<span class="cost"></span></div>' +
                '</div>' +
                '<div class="row-actions"><button type="button" class="edit-btn">Edit</button></div>';

            card.querySelector('.name').textContent = p.name;
            card.querySelector('.stock').textContent = p.stock_qty;
            card.querySelector('.price').textContent = parseFloat(p.selling_price).toFixed(2);
            card.querySelector('.cost').textContent = parseFloat(p.cost_price).toFixed(2);

            const editBtn = card.querySelector('.edit-btn');
            editBtn.setAttribute('data-product-id', String(p.id));
            editBtn.addEventListener('click', function (e) {
                e.preventDefault();
                const pid = parseInt(this.getAttribute('data-product-id'), 10);
                if (typeof window.startEditProduct === 'function') {
                    window.startEditProduct(pid);
                    const formCard = document.getElementById('product-form-card');
                    if (formCard) {
                        formCard.style.setProperty('display', 'block', 'important');
                        formCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }
            });

            list.appendChild(card);
        });

        const search = document.getElementById('admin-product-search');
        if (search && search.value.trim()) {
            filterMobileProducts(search.value.trim().toLowerCase());
        }
    }

    function initAdminAndroidUi() {
        if (!document.body.classList.contains('page-admin')) return;
        if (!isPosAndroidApp()) return;

        document.documentElement.classList.add('pos-android-app');
        document.body.classList.add('pos-android-app');

        syncMobileHeader();
        wireMobileToolbar();
        wireMobileActions();
        setupProductSearch();

        if (typeof window.adminProducts !== 'undefined' && window.adminProducts.length) {
            renderAdminProductsMobile(window.adminProducts);
        }
    }

    window.isPosAndroidApp = isPosAndroidApp;
    window.initAdminAndroidUi = initAdminAndroidUi;
    window.renderAdminProductsMobile = renderAdminProductsMobile;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAdminAndroidUi);
    } else {
        initAdminAndroidUi();
    }
})();

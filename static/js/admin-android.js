/**
 * Admin page layout for POS Android WebView (body.pos-android-app).
 */
(function () {
    'use strict';

    var androidUiInitialized = false;

    function isPosAndroidApp() {
        if (typeof window.isPosAndroidWebView === 'function') {
            return window.isPosAndroidWebView();
        }
        return false;
    }

    function bindAndroidTap(el, handler) {
        if (!el || el.dataset.posAndroidBound === '1') return;
        el.dataset.posAndroidBound = '1';
        function run(e) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            handler(e);
        }
        el.addEventListener('click', run, true);
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

    /** Place add-product form directly under the mobile search bar. */
    function relocateProductFormForAndroid() {
        const form = document.getElementById('product-form-card');
        const anchor = document.querySelector('.admin-mobile-search-wrap');
        if (!form || !anchor || form.dataset.posAndroidRelocated === '1') return;
        anchor.insertAdjacentElement('afterend', form);
        form.dataset.posAndroidRelocated = '1';
    }

    function isProductFormVisible() {
        const formCard = document.getElementById('product-form-card');
        if (!formCard) return false;
        return window.getComputedStyle(formCard).display !== 'none';
    }

    function toggleAndroidProductForm() {
        if (typeof window.showProductForm === 'function') {
            if (isProductFormVisible()) {
                if (typeof window.clearProductForm === 'function') {
                    window.clearProductForm();
                }
            } else {
                window.showProductForm();
                const formCard = document.getElementById('product-form-card');
                if (formCard) {
                    setTimeout(function () {
                        formCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }, 80);
                }
            }
            return;
        }
        const hiddenBtn = document.getElementById('btn-show-product-form');
        if (hiddenBtn) hiddenBtn.click();
    }

    function toggleAndroidShifts() {
        if (typeof window.toggleShiftsPanel === 'function') {
            window.toggleShiftsPanel();
            return;
        }
        const hiddenBtn = document.getElementById('btn-toggle-shifts');
        if (hiddenBtn) hiddenBtn.click();
    }

    function wireMobileToolbar() {
        const addMobile = document.getElementById('btn-show-product-form-mobile');
        const importMobile = document.getElementById('btn-import-inventory-mobile');
        const priceListMobile = document.getElementById('btn-price-list-pdf-mobile');

        bindAndroidTap(addMobile, toggleAndroidProductForm);

        bindAndroidTap(priceListMobile, function () {
            if (typeof window.exportPriceListPDF === 'function') {
                window.exportPriceListPDF();
                return;
            }
            const btn = document.getElementById('btn-price-list-pdf');
            if (btn) btn.click();
        });

        bindAndroidTap(importMobile, function () {
            if (typeof window.showImportModal === 'function') {
                window.showImportModal();
                return;
            }
            const btn = document.getElementById('btn-import-inventory');
            if (btn) btn.click();
        });
    }

    function wireMobileActions() {
        const actions = [
            { id: 'admin-action-settings', fn: function () { navigate('/store-settings'); } },
            {
                id: 'admin-action-report',
                fn: function () {
                    if (typeof window.toggleReportPanel === 'function') {
                        window.toggleReportPanel();
                    }
                },
            },
            { id: 'admin-action-withdrawals', fn: function () { navigate('/withdrawals/history'); } },
            { id: 'admin-action-analytics', fn: function () { navigate('/analytics'); } },
            { id: 'admin-action-shifts', fn: toggleAndroidShifts },
            { id: 'admin-action-pending', fn: function () { navigate('/pending-collection'); } },
            { id: 'admin-action-billing', fn: function () { navigate('/billing'); } },
        ];
        actions.forEach(function (a) {
            const btn = document.getElementById(a.id);
            bindAndroidTap(btn, a.fn);
        });
    }

    function wireShiftsPanelAndroid() {
        const panel = document.getElementById('shifts-panel');
        if (!panel || panel.dataset.posAndroidShiftBound === '1') return;
        panel.dataset.posAndroidShiftBound = '1';

        const closeBtn = document.getElementById('btn-close-shifts');
        const startBtn = document.getElementById('btn-start-shift');
        const endBtn = document.getElementById('btn-end-shift');
        const closeReportBtn = document.getElementById('btn-close-shift-report');
        const closePwdBtn = document.getElementById('btn-close-shift-password-modal');
        const verifyPwdBtn = document.getElementById('btn-verify-shift-password');
        const pwdInput = document.getElementById('shift-admin-password');

        function closeShifts() {
            const backdrop = document.getElementById('panel-backdrop');
            panel.style.setProperty('display', 'none', 'important');
            if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
        }

        bindAndroidTap(closeBtn, closeShifts);
        bindAndroidTap(startBtn, function () {
            if (typeof window.startShift === 'function') window.startShift();
        });
        bindAndroidTap(endBtn, function () {
            if (typeof window.endShift === 'function') window.endShift();
        });
        bindAndroidTap(closeReportBtn, function () {
            const report = document.getElementById('shift-report-panel');
            const backdrop = document.getElementById('panel-backdrop');
            if (report) report.style.setProperty('display', 'none', 'important');
            if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
        });
        bindAndroidTap(closePwdBtn, function () {
            if (typeof window.hideShiftPasswordModal === 'function') {
                window.hideShiftPasswordModal();
            }
            const backdrop = document.getElementById('panel-backdrop');
            if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
        });
        bindAndroidTap(verifyPwdBtn, function () {
            if (typeof window.verifyShiftPassword === 'function') window.verifyShiftPassword();
        });
        if (pwdInput && pwdInput.dataset.posAndroidBound !== '1') {
            pwdInput.dataset.posAndroidBound = '1';
            pwdInput.addEventListener('keypress', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (typeof window.verifyShiftPassword === 'function') {
                        window.verifyShiftPassword();
                    }
                }
            });
        }
    }

    function wireProductFormAndroid() {
        const saveBtn = document.getElementById('btn-save-product');
        const clearBtn = document.getElementById('btn-clear-product');
        bindAndroidTap(saveBtn, function () {
            if (typeof window.saveProduct === 'function') window.saveProduct();
        });
        bindAndroidTap(clearBtn, function () {
            if (typeof window.clearProductForm === 'function') window.clearProductForm();
        });
    }

    function setupProductSearch() {
        const input = document.getElementById('admin-product-search');
        if (!input) return;
        if (input.dataset.posAndroidBound === '1') return;
        input.dataset.posAndroidBound = '1';
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

    function wireImportModalAndroid() {
        const uploadBtn = document.getElementById('btn-upload-inventory');
        const chooseBtn = document.getElementById('btn-choose-file');
        const fileLabel = document.getElementById('inventory-file-label');

        function runUpload(e) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            if (typeof window.handleImportUploadClick === 'function') {
                window.handleImportUploadClick(e);
            } else if (typeof window.uploadInventoryFile === 'function') {
                window.uploadInventoryFile(e);
            }
        }

        if (uploadBtn && uploadBtn.dataset.posAndroidUploadBound !== '1') {
            uploadBtn.dataset.posAndroidUploadBound = '1';
            uploadBtn.addEventListener('click', runUpload, true);
        }
        bindAndroidTap(chooseBtn, function () {
            const input = document.getElementById('inventory-file-input');
            if (input) input.click();
        });
        bindAndroidTap(fileLabel, function () {
            const input = document.getElementById('inventory-file-input');
            if (input) input.click();
        });
    }

    function initAdminAndroidUi() {
        if (!document.body.classList.contains('page-admin')) return;
        if (!isPosAndroidApp()) return;
        if (androidUiInitialized) {
            syncMobileHeader();
            const products = window.adminProducts;
            if (products && products.length) {
                renderAdminProductsMobile(products);
            }
            return;
        }
        androidUiInitialized = true;

        syncMobileHeader();
        relocateProductFormForAndroid();
        wireMobileToolbar();
        wireMobileActions();
        wireImportModalAndroid();
        wireShiftsPanelAndroid();
        wireProductFormAndroid();
        setupProductSearch();

        const products = window.adminProducts;
        if (products && products.length) {
            renderAdminProductsMobile(products);
        }
    }

    window.isPosAndroidApp = isPosAndroidApp;
    window.initAdminAndroidUi = initAdminAndroidUi;
    window.renderAdminProductsMobile = renderAdminProductsMobile;
    window.toggleAndroidProductForm = toggleAndroidProductForm;
    window.toggleAndroidShifts = toggleAndroidShifts;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAdminAndroidUi);
    } else {
        initAdminAndroidUi();
    }
})();

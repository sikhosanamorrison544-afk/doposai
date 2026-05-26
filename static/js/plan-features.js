/**
 * Plan-based feature gates (Starter / Business / Pro). Trial = all features.
 */
(function (global) {
    'use strict';

    const STORAGE_KEY = 'pos_plan_features';
    const STORAGE_PLAN = 'pos_effective_plan';

    let features = null;
    let effectivePlan = 'starter';
    let loaded = false;

    function cacheFromSubscription(sub) {
        if (!sub) return;
        features = Array.isArray(sub.features) ? sub.features.slice() : [];
        effectivePlan = sub.effective_plan || sub.plan || 'starter';
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(features));
            sessionStorage.setItem(STORAGE_PLAN, effectivePlan);
        } catch (e) {}
        loaded = true;
    }

    function loadFromStorage() {
        try {
            const raw = sessionStorage.getItem(STORAGE_KEY);
            if (raw) features = JSON.parse(raw);
            effectivePlan = sessionStorage.getItem(STORAGE_PLAN) || 'starter';
            loaded = features !== null;
        } catch (e) {
            features = [];
        }
    }

    function hasFeature(name) {
        if (!name) return true;
        if (!features) loadFromStorage();
        if (!features || !features.length) return false;
        return features.indexOf(name) >= 0;
    }

    function requiredPlanLabel(feature) {
        const pro = ['accounting', 'enterprise', 'ai_assistant'];
        return pro.indexOf(feature) >= 0 ? 'Pro' : 'Business';
    }

    function showUpgradeToast(feature) {
        const label = requiredPlanLabel(feature);
        const msg =
            'This feature requires the ' +
            label +
            ' plan. Open Subscription & Billing to upgrade.';
        if (typeof alert === 'function') {
            alert(msg);
        }
    }

    /** Hide nav / buttons that require a feature. */
    function applyNavGates() {
        const map = {
            'btn-layby': 'layby',
            'btn-toggle-layby': 'layby',
            'btn-pending-collection': 'pending_collection',
            'btn-withdraw': 'withdrawals',
            'btn-analytics': 'analytics',
            'admin-action-analytics': 'analytics',
            'btn-accounting': 'accounting',
            'btn-enterprise': 'enterprise',
            'admin-action-enterprise': 'enterprise',
            'btn-toggle-shifts': 'shifts',
            'admin-action-shifts': 'shifts',
            'btn-sync-withdrawals-backup': 'backup_sync',
            'btn-import-inventory': 'product_import',
        };
        Object.keys(map).forEach(function (id) {
            const el = document.getElementById(id);
            if (!el) return;
            const feat = map[id];
            if (hasFeature(feat)) {
                return;
            }
            el.style.display = 'none';
            el.setAttribute('data-plan-locked', feat);
        });
        document.querySelectorAll('[data-require-feature]').forEach(function (el) {
            const feat = el.getAttribute('data-require-feature');
            if (!hasFeature(feat)) {
                el.style.display = 'none';
            }
        });
        if (!hasFeature('layby')) {
            const laybyContainer = document.getElementById('layby-sections-container');
            if (laybyContainer) laybyContainer.style.display = 'none';
        }
    }

    /** Block page if opened directly without the feature. */
    function guardCurrentPage(feature) {
        if (hasFeature(feature)) return true;
        showUpgradeToast(feature);
        const isAdmin = (function () {
            try {
                const u = JSON.parse(localStorage.getItem('pos_user') || '{}');
                return u && u.role === 'admin';
            } catch (e) {
                return false;
            }
        })();
        if (isAdmin) {
            window.location.href = '/billing?upgrade=' + encodeURIComponent(feature);
        } else {
            window.location.href = '/';
        }
        return false;
    }

    const PAGE_FEATURES = {
        '/analytics': 'analytics',
        '/accounting': 'accounting',
        '/enterprise': 'enterprise',
        '/layby': 'layby',
        '/quotations': 'quotations',
        '/pending-collection': 'pending_collection',
        '/debts/outstanding': 'outstanding_debts',
        '/withdrawals/history': 'withdrawals',
    };

    function guardPageByPath() {
        const path = window.location.pathname.replace(/\/$/, '') || '/';
        for (const prefix in PAGE_FEATURES) {
            if (path === prefix || path.indexOf(prefix + '/') === 0) {
                return guardCurrentPage(PAGE_FEATURES[prefix]);
            }
        }
        return true;
    }

    async function loadFromApi(apiFn) {
        try {
            const sub = await apiFn('/api/subscriptions/status');
            cacheFromSubscription(sub);
            return sub;
        } catch (e) {
            loadFromStorage();
            throw e;
        }
    }

    function wrapApi(apiFn) {
        return async function (path, options) {
            try {
                return await apiFn(path, options);
            } catch (err) {
                if (err && err.status === 403 && err.body && err.body.code === 'plan_feature_locked') {
                    showUpgradeToast(err.body.feature);
                    const isAdmin = (function () {
                        try {
                            const u = JSON.parse(localStorage.getItem('pos_user') || '{}');
                            return u && u.role === 'admin';
                        } catch (e2) {
                            return false;
                        }
                    })();
                    if (isAdmin) {
                        window.location.href = '/billing?upgrade=' + encodeURIComponent(err.body.feature || '');
                    }
                }
                throw err;
            }
        };
    }

    function patchFetchForPlanErrors() {
        const orig = global.fetch;
        if (!orig || orig._posPlanPatched) return;
        global.fetch = async function (input, init) {
            const res = await orig(input, init);
            if (res.status === 403) {
                try {
                    const clone = res.clone();
                    const data = await clone.json();
                    if (data && data.code === 'plan_feature_locked') {
                        showUpgradeToast(data.feature);
                    }
                } catch (e) {}
            }
            return res;
        };
        global.fetch._posPlanPatched = true;
    }

    global.posPlanFeatures = {
        loadFromApi: loadFromApi,
        loadFromStorage: loadFromStorage,
        cacheFromSubscription: cacheFromSubscription,
        hasFeature: hasFeature,
        getEffectivePlan: function () {
            return effectivePlan;
        },
        applyNavGates: applyNavGates,
        guardPageByPath: guardPageByPath,
        guardCurrentPage: guardCurrentPage,
        wrapApi: wrapApi,
        patchFetchForPlanErrors: patchFetchForPlanErrors,
    };

    loadFromStorage();
    patchFetchForPlanErrors();

    function bootstrapPlanFeatures() {
        const t = localStorage.getItem('pos_token');
        if (!t) return;
        const apiFn = function (path) {
            return fetch(path, {
                headers: { Authorization: 'Bearer ' + t, Accept: 'application/json' },
            }).then(function (res) {
                if (!res.ok) throw new Error('status');
                return res.json();
            });
        };
        loadFromApi(apiFn)
            .then(function () {
                applyNavGates();
                guardPageByPath();
            })
            .catch(function () {
                loadFromStorage();
                applyNavGates();
                guardPageByPath();
            });
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', bootstrapPlanFeatures);
        } else {
            bootstrapPlanFeatures();
        }
    }
})(typeof window !== 'undefined' ? window : global);

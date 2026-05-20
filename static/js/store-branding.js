(function () {
    'use strict';

    const TOKEN_KEY = 'pos_token';
    const CACHE_KEY = 'pos_store_branding';
    const TTL_MS = 5 * 60 * 1000;

    function applyName(name) {
        if (!name || typeof name !== 'string') return;
        const clean = name.trim();
        if (!clean) return;

        document.querySelectorAll('.shop-name').forEach(function (el) {
            const suffix = (el.dataset && el.dataset.branding === 'suffix' && el.dataset.suffix)
                ? el.dataset.suffix
                : '';
            el.textContent = suffix ? `${clean} ${suffix}` : clean;
        });

        try {
            const currentTitle = document.title || '';
            if (currentTitle.includes(' | ')) {
                document.title = `${currentTitle.split(' | ').slice(0, -1).join(' | ')} | ${clean}`;
            } else if (currentTitle && !currentTitle.includes(clean)) {
                document.title = `${currentTitle} | ${clean}`;
            }
        } catch (_) { /* ignore title failures */ }
    }

    function readCache() {
        try {
            const raw = localStorage.getItem(CACHE_KEY);
            if (!raw) return null;
            const obj = JSON.parse(raw);
            if (!obj || typeof obj !== 'object') return null;
            if (!obj.store_name) return null;
            return obj;
        } catch (_) {
            return null;
        }
    }

    function writeCache(obj) {
        try {
            localStorage.setItem(CACHE_KEY, JSON.stringify({
                store_name: obj.store_name || '',
                ts: Date.now(),
            }));
        } catch (_) { /* storage may be full or disabled */ }
    }

    function isFresh(cache) {
        return cache && cache.ts && (Date.now() - cache.ts) < TTL_MS;
    }

    async function fetchFresh() {
        const token = localStorage.getItem(TOKEN_KEY);
        if (!token) return null;
        try {
            const res = await fetch('/api/store-settings', {
                headers: { 'Authorization': `Bearer ${token}` },
                credentials: 'same-origin',
            });
            if (!res.ok) return null;
            const data = await res.json();
            if (data && data.store_name) {
                writeCache({ store_name: data.store_name });
                return data.store_name;
            }
            return null;
        } catch (_) {
            return null;
        }
    }

    async function refresh() {
        const cached = readCache();
        if (cached && cached.store_name) {
            applyName(cached.store_name);
        }
        if (!isFresh(cached)) {
            const fresh = await fetchFresh();
            if (fresh) applyName(fresh);
        }
    }

    window.PosBranding = {
        refresh,
        apply: applyName,
        clearCache: function () {
            try { localStorage.removeItem(CACHE_KEY); } catch (_) { /* noop */ }
        },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', refresh);
    } else {
        refresh();
    }
})();

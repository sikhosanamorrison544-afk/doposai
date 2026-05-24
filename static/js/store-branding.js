(function () {
    'use strict';

    const TOKEN_KEY = 'pos_token';
    const CACHE_KEY = 'pos_store_branding';
    const TTL_MS = 5 * 60 * 1000;
    const DEFAULT_MOTTO = 'Pecunia Non Olet';

    function readMottoMeta() {
        const meta = document.querySelector('meta[name="platform-motto"]');
        if (!meta || !meta.content) return '';
        return meta.content.trim();
    }

    function resolveMotto(preferred) {
        const candidate = (preferred || readMottoMeta() || DEFAULT_MOTTO).trim();
        return candidate || DEFAULT_MOTTO;
    }

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

    function applyMotto(motto) {
        const text = resolveMotto(motto);
        window.__PLATFORM_MOTTO__ = text;

        document.querySelectorAll('.platform-motto').forEach(function (el) {
            if (!el.textContent || !el.textContent.trim()) {
                el.textContent = text;
            }
        });

        document.querySelectorAll('.top-bar').forEach(function (bar) {
            if (bar.querySelector('.platform-motto')) return;
            const shop = bar.querySelector('.shop-name');
            if (!shop) return;
            let brand = shop.parentElement;
            if (!brand || !brand.classList.contains('top-bar-brand')) {
                brand = document.createElement('div');
                brand.className = 'top-bar-brand';
                shop.parentNode.insertBefore(brand, shop);
                brand.appendChild(shop);
            }
            const span = document.createElement('span');
            span.className = 'platform-motto';
            span.textContent = text;
            brand.appendChild(span);
        });

        document.querySelectorAll('.pa-mobile-header').forEach(function (hdr) {
            if (hdr.querySelector('.platform-motto')) return;
            const sub = hdr.querySelector('.pa-mobile-subtitle');
            if (!sub) return;
            const p = document.createElement('p');
            p.className = 'platform-motto platform-motto--mobile';
            p.textContent = text;
            sub.insertAdjacentElement('afterend', p);
        });

        const login = document.getElementById('login-screen');
        if (login && !login.querySelector('.platform-motto')) {
            const p = document.createElement('p');
            p.className = 'platform-motto platform-motto--login';
            p.textContent = text;
            const h1 = login.querySelector('h1');
            if (h1) h1.insertAdjacentElement('afterend', p);
        }
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

    async function fetchPlatformInfo() {
        try {
            const res = await fetch('/api/platform-info', { credentials: 'same-origin' });
            if (!res.ok) return null;
            return await res.json();
        } catch (_) {
            return null;
        }
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
        applyMotto();

        const platform = await fetchPlatformInfo();
        if (platform && platform.motto) {
            applyMotto(platform.motto);
        }

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
        applyMotto,
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

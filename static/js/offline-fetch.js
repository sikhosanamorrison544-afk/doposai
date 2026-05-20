/**
 * Offline mutation queue for WebView (Android bridge) and browser localStorage fallback.
 * Patches fetch() for same-origin /api/ POST/PUT/PATCH/DELETE when offline.
 */
(function () {
    'use strict';

    const LS_KEY = 'pos_offline_mutations';
    const MUTATION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

    function isApiMutation(url, method) {
        if (!MUTATION_METHODS.has(method)) return false;
        try {
            const u = new URL(url, window.location.origin);
            return u.origin === window.location.origin && u.pathname.startsWith('/api/');
        } catch (_) {
            return false;
        }
    }

    function mutationPath(url) {
        const u = new URL(url, window.location.origin);
        return u.pathname + (u.search || '');
    }

    function queueLocal(entry) {
        const q = JSON.parse(localStorage.getItem(LS_KEY) || '[]');
        q.push({ ...entry, createdAt: Date.now() });
        localStorage.setItem(LS_KEY, JSON.stringify(q));
    }

    async function queueOffline(method, url, init) {
        const path = mutationPath(url);
        const body = typeof init?.body === 'string' ? init.body : null;
        const contentType = (init?.headers && (init.headers['Content-Type'] || init.headers['content-type'])) || 'application/json';

        if (typeof PosAndroidOffline !== 'undefined' && PosAndroidOffline.queueMutation) {
            const payload = JSON.stringify({ method, path, body, contentType });
            const res = JSON.parse(PosAndroidOffline.queueMutation(payload) || '{}');
            if (res.ok) {
                return new Response(
                    JSON.stringify({ ok: true, offline_queued: true, id: res.id, message: 'Saved offline' }),
                    { status: 202, headers: { 'Content-Type': 'application/json' } }
                );
            }
        }

        queueLocal({ method, path, body, contentType });
        return new Response(
            JSON.stringify({ ok: true, offline_queued: true, message: 'Saved offline (browser queue)' }),
            { status: 202, headers: { 'Content-Type': 'application/json' } }
        );
    }

    function shouldQueueOffline() {
        if (typeof PosAndroidOffline !== 'undefined' && PosAndroidOffline.isOnline) {
            try {
                return PosAndroidOffline.isOnline() !== true;
            } catch (_) { /* fall through */ }
        }
        return !navigator.onLine;
    }

    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
        const url = typeof input === 'string' ? input : input.url;
        const method = ((init && init.method) || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        if (isApiMutation(url, method) && shouldQueueOffline()) {
            let bodyStr = init?.body;
            if (input instanceof Request && !bodyStr) {
                try {
                    bodyStr = await input.clone().text();
                } catch (_) { /* ignore */ }
            }
            return queueOffline(method, url, { ...init, body: bodyStr });
        }
        return nativeFetch(input, init);
    };

    /** Replay browser localStorage queue when back online (non-Android or fallback). */
    async function flushLocalQueue() {
        const token = localStorage.getItem('pos_token');
        if (!token || !navigator.onLine) return;
        const q = JSON.parse(localStorage.getItem(LS_KEY) || '[]');
        if (!q.length) return;
        const remaining = [];
        for (const m of q) {
            try {
                const res = await nativeFetch(m.path, {
                    method: m.method,
                    headers: {
                        Authorization: 'Bearer ' + token,
                        'Content-Type': m.contentType || 'application/json',
                    },
                    body: m.body || undefined,
                });
                if (!res.ok) remaining.push(m);
            } catch (_) {
                remaining.push(m);
            }
        }
        localStorage.setItem(LS_KEY, JSON.stringify(remaining));
    }

    window.addEventListener('online', () => {
        flushLocalQueue().catch(() => {});
    });

    window.posOfflineFetch = { flushLocalQueue, shouldQueueOffline };
})();

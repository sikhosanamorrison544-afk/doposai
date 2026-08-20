/**
 * POS service worker — password-reset isolation.
 *
 * CACHE_VERSION must be bumped when this file's fetch policy changes.
 * Password-reset routes and any URL containing a reset token are network-only
 * and must never enter Cache Storage.
 *
 * Does not touch IndexedDB or localStorage (offline sales stay intact).
 */
/* eslint-disable no-restricted-globals */
const CACHE_VERSION = 'pos-sw-v3-password-reset-isolation';

const PASSWORD_RESET_PATHS = [
    '/reset-password',
    '/auth/reset-password',
    '/auth/reset-password/validate',
];

function isPasswordResetRequest(urlString) {
    try {
        const u = new URL(urlString, self.location.origin);
        const path = u.pathname || '';
        if (PASSWORD_RESET_PATHS.some(function (p) {
            return path === p || path.indexOf(p + '/') === 0;
        })) {
            return true;
        }
        // Never cache any request that carries a password-reset token.
        if (u.searchParams && u.searchParams.has('token')) {
            if (path.indexOf('reset-password') !== -1 || path.indexOf('/auth/') === 0) {
                return true;
            }
        }
        return false;
    } catch (_) {
        return false;
    }
}

self.addEventListener('install', function (event) {
    self.skipWaiting();
    event.waitUntil(Promise.resolve());
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches
            .keys()
            .then(function (keys) {
                return Promise.all(
                    keys
                        .filter(function (k) {
                            return k !== CACHE_VERSION;
                        })
                        .map(function (k) {
                            return caches.delete(k);
                        })
                );
            })
            .then(function () {
                return self.clients.claim();
            })
    );
});

self.addEventListener('fetch', function (event) {
    const req = event.request;
    if (!req || req.method !== 'GET') {
        return;
    }
    if (isPasswordResetRequest(req.url)) {
        // Network-only: never read/write Cache Storage for reset flows.
        event.respondWith(
            fetch(req, { cache: 'no-store' }).catch(function () {
                return new Response('Offline', { status: 503, statusText: 'Offline' });
            })
        );
        return;
    }
    // Default: network pass-through without caching HTML/API into Cache Storage.
    event.respondWith(fetch(req));
});

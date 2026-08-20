/**
 * Detect deploy upgrades and drop stale HTTP Cache Storage / service workers.
 *
 * Preserves business data:
 * - localStorage keys such as pos_token, pos_user, pos_offline_mutations, pos-theme
 * - IndexedDB / offline sales / sync queues (never touched here)
 *
 * Only clears Cache Storage entries and unregisters service workers, then
 * reloads once when the stamped HTML build id changes.
 *
 * Also registers a root /sw.js that forces network-only handling for
 * password-reset routes so tokens and store identity are never cached.
 */
(function () {
    'use strict';

    var BUILD_KEY = 'pos_client_build';
    var RELOAD_KEY = 'pos_client_build_reload';
    var PASSWORD_RESET_PATH_MARKERS = [
        '/reset-password',
        '/auth/reset-password',
        '/auth/reset-password/validate',
    ];

    function readBuild() {
        try {
            if (window.__POS_BUILD__ && String(window.__POS_BUILD__).trim()) {
                return String(window.__POS_BUILD__).trim();
            }
        } catch (_) { /* ignore */ }
        var meta = document.querySelector('meta[name="pos-build"]');
        if (meta && meta.content) return String(meta.content).trim();
        return '';
    }

    function lsGet(key) {
        try {
            return localStorage.getItem(key);
        } catch (_) {
            return null;
        }
    }

    function lsSet(key, value) {
        try {
            localStorage.setItem(key, value);
        } catch (_) { /* ignore quota / private mode */ }
    }

    function ssGet(key) {
        try {
            return sessionStorage.getItem(key);
        } catch (_) {
            return null;
        }
    }

    function ssSet(key, value) {
        try {
            sessionStorage.setItem(key, value);
        } catch (_) { /* ignore */ }
    }

    function ssRemove(key) {
        try {
            sessionStorage.removeItem(key);
        } catch (_) { /* ignore */ }
    }

    function isPasswordResetPage() {
        try {
            if (document.body && document.body.classList.contains('page-reset-password')) {
                return true;
            }
            return /\/reset-password/i.test(window.location.pathname || '');
        } catch (_) {
            return false;
        }
    }

    function urlLooksLikePasswordReset(url) {
        try {
            var u = new URL(url, window.location.origin);
            var path = u.pathname || '';
            for (var i = 0; i < PASSWORD_RESET_PATH_MARKERS.length; i++) {
                var p = PASSWORD_RESET_PATH_MARKERS[i];
                if (path === p || path.indexOf(p + '/') === 0) return true;
            }
            if (u.searchParams && u.searchParams.has('token')) {
                if (path.indexOf('reset-password') !== -1 || path.indexOf('/auth/') === 0) {
                    return true;
                }
            }
        } catch (_) { /* ignore */ }
        return false;
    }

    function purgePasswordResetFromCaches() {
        if (typeof caches === 'undefined' || !caches.keys) {
            return Promise.resolve();
        }
        return caches
            .keys()
            .then(function (keys) {
                return Promise.all(
                    keys.map(function (cacheName) {
                        return caches.open(cacheName).then(function (cache) {
                            return cache.keys().then(function (requests) {
                                return Promise.all(
                                    requests.map(function (req) {
                                        if (urlLooksLikePasswordReset(req.url)) {
                                            return cache.delete(req);
                                        }
                                        return null;
                                    })
                                );
                            });
                        });
                    })
                );
            })
            .catch(function () {});
    }

    function unregisterAllServiceWorkers() {
        if (!navigator.serviceWorker || !navigator.serviceWorker.getRegistrations) {
            return Promise.resolve();
        }
        return navigator.serviceWorker
            .getRegistrations()
            .then(function (regs) {
                return Promise.all(
                    regs.map(function (r) {
                        return r.unregister();
                    })
                );
            })
            .catch(function () {});
    }

    function registerPasswordResetSafeSw() {
        // Reset pages must not be controlled by any SW (including an older one
        // that still caches branding HTML). Unregister everything here.
        if (isPasswordResetPage()) {
            unregisterAllServiceWorkers();
            return;
        }
        if (!navigator.serviceWorker || !navigator.serviceWorker.register) return;
        try {
            navigator.serviceWorker
                .register('/sw.js', { scope: '/' })
                .catch(function () { /* ignore SW registration failures */ });
        } catch (_) { /* ignore */ }
    }

    function clearAssetCaches() {
        var tasks = [];
        try {
            if (typeof caches !== 'undefined' && caches.keys) {
                tasks.push(
                    caches
                        .keys()
                        .then(function (keys) {
                            return Promise.all(
                                keys.map(function (k) {
                                    return caches.delete(k);
                                })
                            );
                        })
                        .catch(function () {})
                );
            }
        } catch (_) { /* ignore */ }
        try {
            if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
                tasks.push(
                    navigator.serviceWorker
                        .getRegistrations()
                        .then(function (regs) {
                            return Promise.all(
                                regs.map(function (r) {
                                    return r.unregister();
                                })
                            );
                        })
                        .catch(function () {})
                );
            }
        } catch (_) { /* ignore */ }
        return new Promise(function (resolve) {
            var settled = false;
            function done() {
                if (settled) return;
                settled = true;
                resolve();
            }
            setTimeout(done, 750);
            Promise.all(tasks).then(done).catch(done);
        });
    }

    // Always scrub cached password-reset responses (tokens must never linger),
    // even when the HTML build stamp is missing.
    purgePasswordResetFromCaches();

    var build = readBuild();
    if (!build) {
        if (isPasswordResetPage()) {
            unregisterAllServiceWorkers();
        }
        return;
    }
    window.__POS_BUILD__ = build;

    // On the reset page: drop any controlling SW immediately so a stale worker
    // cannot serve old shells that still load shared store branding.
    if (isPasswordResetPage()) {
        unregisterAllServiceWorkers();
    }

    var previous = lsGet(BUILD_KEY);
    if (previous === build) {
        ssRemove(RELOAD_KEY);
        registerPasswordResetSafeSw();
        return;
    }

    // First visit for this profile: record build and clear any leftover Cache Storage
    // (do not reload — avoid surprising first paint). Never touch business keys.
    if (!previous) {
        lsSet(BUILD_KEY, build);
        clearAssetCaches().then(function () {
            registerPasswordResetSafeSw();
        });
        return;
    }

    // Upgrade path: purge asset caches only, then reload once.
    var reloadToken = previous + '->' + build;
    if (ssGet(RELOAD_KEY) === reloadToken) {
        // Already reloaded for this transition; stop loops.
        lsSet(BUILD_KEY, build);
        ssRemove(RELOAD_KEY);
        registerPasswordResetSafeSw();
        return;
    }

    ssSet(RELOAD_KEY, reloadToken);
    // Stamp the new build before reload so a partial failure still advances.
    lsSet(BUILD_KEY, build);
    clearAssetCaches().then(function () {
        try {
            window.location.reload();
        } catch (_) {
            window.location.href = window.location.href.split('#')[0];
        }
    });
})();

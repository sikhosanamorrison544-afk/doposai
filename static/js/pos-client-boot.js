/**
 * Detect deploy upgrades and drop stale HTTP Cache Storage / service workers.
 *
 * Preserves business data:
 * - localStorage keys such as pos_token, pos_user, pos_offline_mutations, pos-theme
 * - IndexedDB / offline sales / sync queues (never touched here)
 *
 * Only clears Cache Storage entries and unregisters service workers, then
 * reloads once when the stamped HTML build id changes.
 */
(function () {
    'use strict';

    var BUILD_KEY = 'pos_client_build';
    var RELOAD_KEY = 'pos_client_build_reload';

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
        // Bound wait — some WebViews hang on Cache Storage APIs.
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

    var build = readBuild();
    if (!build) return;
    window.__POS_BUILD__ = build;

    var previous = lsGet(BUILD_KEY);
    if (previous === build) {
        ssRemove(RELOAD_KEY);
        return;
    }

    // First visit for this profile: record build and clear any leftover Cache Storage
    // (do not reload — avoid surprising first paint). Never touch business keys.
    if (!previous) {
        lsSet(BUILD_KEY, build);
        clearAssetCaches();
        return;
    }

    // Upgrade path: purge asset caches only, then reload once.
    var reloadToken = previous + '->' + build;
    if (ssGet(RELOAD_KEY) === reloadToken) {
        // Already reloaded for this transition; stop loops.
        lsSet(BUILD_KEY, build);
        ssRemove(RELOAD_KEY);
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

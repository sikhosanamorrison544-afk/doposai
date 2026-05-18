/**
 * Shared helpers for pages opened in the POS Android WebView.
 */
(function () {
    'use strict';

    function isPosAndroidApp() {
        try {
            if (localStorage.getItem('pos_android_app') === '1') return true;
        } catch (e) { /* ignore */ }
        return document.body && document.body.classList.contains('pos-android-app');
    }

    function markPosAndroidApp() {
        document.documentElement.classList.add('pos-android-app');
        if (document.body) document.body.classList.add('pos-android-app');
        try {
            localStorage.setItem('pos_android_app', '1');
        } catch (e) { /* ignore */ }
    }

    function fullWebUrl(path) {
        const p = path && path.charAt(0) === '/' ? path : '/' + (path || '');
        return window.location.origin + p;
    }

    function openFullWebVersion(path) {
        const url = fullWebUrl(path);
        try {
            if (typeof PosAndroidUi !== 'undefined' && PosAndroidUi.openExternalUrl) {
                PosAndroidUi.openExternalUrl(url);
                return;
            }
        } catch (e) { /* ignore */ }
        window.open(url, '_blank');
    }

    function wireWebVersionButton(buttonId, path) {
        const btn = document.getElementById(buttonId);
        if (!btn) return;
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            openFullWebVersion(path);
        });
    }

    window.isPosAndroidApp = isPosAndroidApp;
    window.markPosAndroidApp = markPosAndroidApp;
    window.openFullWebVersion = openFullWebVersion;
    window.wireWebVersionButton = wireWebVersionButton;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', markPosAndroidApp);
    } else {
        markPosAndroidApp();
    }
})();

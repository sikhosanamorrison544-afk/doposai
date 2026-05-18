/**
 * Android WebView helpers only — must NOT activate on desktop/mobile browsers.
 * Detection: native bridge, WebView-injected flag, or app user-agent suffix.
 */
(function () {
    'use strict';

    var UA_MARKER = 'DoPosPOS-Android';

    function hasNativeBridge() {
        try {
            return typeof PosAndroidUi !== 'undefined' && PosAndroidUi !== null;
        } catch (e) {
            return false;
        }
    }

    function isPosAndroidWebView() {
        if (window.__POS_ANDROID_WEBVIEW__ === true) {
            return true;
        }
        if (hasNativeBridge()) {
            return true;
        }
        return new RegExp(UA_MARKER, 'i').test(navigator.userAgent || '');
    }

    /** Called from Android WebView after each page load. */
    function markPosAndroidWebView() {
        window.__POS_ANDROID_WEBVIEW__ = true;
        document.documentElement.classList.add('pos-android-app');
        if (document.body) {
            document.body.classList.add('pos-android-app');
        }
    }

    /** Strip stale Android layout flags when viewing the site in a normal browser. */
    function ensureDesktopWebLayout() {
        if (isPosAndroidWebView()) {
            return;
        }
        try {
            localStorage.removeItem('pos_android_app');
        } catch (e) { /* ignore */ }
        document.documentElement.classList.remove('pos-android-app');
        if (document.body) {
            document.body.classList.remove('pos-android-app');
        }
    }

    function fullWebUrl(path) {
        var p = path && path.charAt(0) === '/' ? path : '/' + (path || '');
        return window.location.origin + p;
    }

    function openFullWebVersion(path) {
        var url = fullWebUrl(path);
        try {
            if (hasNativeBridge() && PosAndroidUi.openExternalUrl) {
                PosAndroidUi.openExternalUrl(url);
                return;
            }
        } catch (e) { /* ignore */ }
        window.open(url, '_blank');
    }

    function wireWebVersionButton(buttonId, path) {
        var btn = document.getElementById(buttonId);
        if (!btn) return;
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            openFullWebVersion(path);
        });
    }

    window.isPosAndroidApp = isPosAndroidWebView;
    window.isPosAndroidWebView = isPosAndroidWebView;
    window.markPosAndroidApp = markPosAndroidWebView;
    window.markPosAndroidWebView = markPosAndroidWebView;
    window.ensureDesktopWebLayout = ensureDesktopWebLayout;
    window.openFullWebVersion = openFullWebVersion;
    window.wireWebVersionButton = wireWebVersionButton;

    ensureDesktopWebLayout();

    if (/DoPosPOS-Android/i.test(navigator.userAgent || '')) {
        markPosAndroidWebView();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            ensureDesktopWebLayout();
            if (isPosAndroidWebView()) {
                markPosAndroidWebView();
            }
        });
    }
})();

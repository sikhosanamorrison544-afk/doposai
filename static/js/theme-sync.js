/**
 * Keep theme in sync when changed from POS/admin or another tab.
 */
(function () {
    'use strict';

    function applyTheme(themeName) {
        const theme = themeName || 'default';
        const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
        document.body.classList.remove(...themeClasses);
        document.documentElement.classList.remove(...themeClasses);
        const cls = 'theme-' + theme;
        document.body.classList.add(cls);
        document.documentElement.classList.add(cls);
        if (theme === 'light') {
            if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
        } else if (typeof window.hideLightThemeVideo === 'function') {
            window.hideLightThemeVideo();
        }
        try {
            localStorage.setItem('pos-theme', theme);
        } catch (e) {}
    }

    function loadTheme() {
        const saved = localStorage.getItem('pos-theme') || 'default';
        const valid = ['default', 'light', 'classic'].includes(saved) ? saved : 'default';
        applyTheme(valid);
    }

    window.posApplyTheme = applyTheme;
    window.posLoadTheme = loadTheme;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadTheme);
    } else {
        loadTheme();
    }

    window.addEventListener('storage', function (e) {
        if (e.key === 'pos-theme') applyTheme(e.newValue || 'default');
    });

    let lastTheme = localStorage.getItem('pos-theme') || 'default';
    setInterval(function () {
        const current = localStorage.getItem('pos-theme') || 'default';
        if (current !== lastTheme) {
            lastTheme = current;
            applyTheme(current);
        }
    }, 500);
})();

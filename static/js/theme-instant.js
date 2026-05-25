/**
 * Apply saved POS theme before first paint (include as first script in <head>).
 */
(function () {
    'use strict';
    try {
        const savedTheme = localStorage.getItem('pos-theme') || 'default';
        const validTheme = ['default', 'light', 'classic'].includes(savedTheme) ? savedTheme : 'default';
        if (validTheme !== savedTheme) {
            try {
                localStorage.setItem('pos-theme', validTheme);
            } catch (e) {}
        }
        const themeClass = 'theme-' + validTheme;
        const themeBackgrounds = {
            default:
                'linear-gradient(135deg, #667eea 0%, #764ba2 25%, #f093fb 50%, #4facfe 75%, #00f2fe 100%)',
            light: 'transparent',
            classic: '#e8e8e8',
        };

        function applyThemeClasses(el) {
            if (!el) return;
            el.className = el.className.replace(/\btheme-\w+/g, '').trim();
            if (themeClass) el.className = (el.className + ' ' + themeClass).trim();
        }
        applyThemeClasses(document.documentElement);
        if (document.body) {
            applyThemeClasses(document.body);
        } else if (document.readyState === 'loading') {
            document.addEventListener(
                'DOMContentLoaded',
                function () {
                    if (document.body) applyThemeClasses(document.body);
                },
                { once: true }
            );
        } else {
            setTimeout(function () {
                if (document.body) applyThemeClasses(document.body);
            }, 0);
        }

        const bg = themeBackgrounds[validTheme] || themeBackgrounds.default;
        const style = document.createElement('style');
        style.id = 'theme-instant';
        style.setAttribute('data-theme', validTheme);
        if (bg === 'transparent') {
            style.textContent =
                'html,body{background:transparent!important;min-height:100vh!important;margin:0!important;padding:0!important;}';
        } else if (validTheme === 'default') {
            style.textContent =
                'html,body{background:transparent!important;background-size:400% 400%!important;min-height:100vh!important;margin:0!important;padding:0!important;position:relative!important;}html::before,body::before{content:"";position:fixed;top:0;left:0;width:100%;height:100%;background:' +
                bg +
                ';background-size:400% 400%;opacity:0.5;z-index:-2;pointer-events:none;}';
        } else {
            style.textContent =
                'html,body{background:' + bg + '!important;min-height:100vh!important;margin:0!important;padding:0!important;}';
        }
        if (document.head.firstChild) {
            document.head.insertBefore(style, document.head.firstChild);
        } else {
            document.head.appendChild(style);
        }
    } catch (e) {}
})();

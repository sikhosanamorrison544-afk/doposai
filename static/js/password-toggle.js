/**
 * Accessible show/hide controls for password fields.
 * Auto-enhances existing and dynamically added inputs (except honeypots).
 */
(function (global) {
    'use strict';

    var EYE =
        '<svg class="pw-toggle-icon pw-toggle-icon-show" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<path fill="currentColor" d="M12 5c-7 0-10 7-10 7s3 7 10 7 10-7 10-7-3-7-10-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/>' +
        '</svg>';
    var EYE_OFF =
        '<svg class="pw-toggle-icon pw-toggle-icon-hide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<path fill="currentColor" d="M2.1 3.51 3.5 2.1l18.4 18.39-1.41 1.41-3.13-3.12A11.5 11.5 0 0 1 12 19c-7 0-10-7-10-7a18.9 18.9 0 0 1 5.05-5.66L2.1 3.51zM12 7a5 5 0 0 1 4.9 4.02l-1.57-1.57A3 3 0 0 0 12 9c-.4 0-.78.08-1.13.23L9.3 7.66A4.9 4.9 0 0 1 12 7zm10 5s-1.16 2.7-3.7 4.66l-1.45-1.45C18.3 14.1 19.6 12.8 20.5 12c-.7-.9-2.4-2.9-4.9-3.9l-1.6 1.6A5 5 0 0 1 12 17a4.95 4.95 0 0 1-2.2-.52l-1.6 1.6C9.4 18.6 10.65 19 12 19c3.3 0 5.9-1.5 7.7-3.05.9-.78 1.6-1.55 2.05-2.1.15-.18.25-.35.25-.85z"/>' +
        '</svg>';

    function shouldSkip(input) {
        if (!input || input.tagName !== 'INPUT') return true;
        if (input.getAttribute('data-no-toggle') === '1') return true;
        if (input.classList && input.classList.contains('pw-no-toggle')) return true;
        var name = (input.getAttribute('name') || '').toLowerCase();
        if (name.indexOf('fake') !== -1) return true;
        var style = input.getAttribute('style') || '';
        if (/left:\s*-9999|opacity:\s*0|display:\s*none/i.test(style)) return true;
        if (input.tabIndex === -1 && input.getAttribute('aria-hidden') === 'true') return true;
        if (input.closest && input.closest('.pw-field')) return true;
        return false;
    }

    function setVisible(input, btn, visible) {
        input.type = visible ? 'text' : 'password';
        btn.setAttribute('aria-pressed', visible ? 'true' : 'false');
        btn.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
        btn.title = visible ? 'Hide password' : 'Show password';
        btn.classList.toggle('is-visible', visible);
    }

    function enhance(input) {
        if (shouldSkip(input)) return;
        if (input.dataset.pwToggleBound === '1') return;
        input.dataset.pwToggleBound = '1';

        var wrap = document.createElement('div');
        wrap.className = 'pw-field';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'pw-toggle';
        btn.innerHTML = EYE + EYE_OFF;
        setVisible(input, btn, false);

        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var show = input.type === 'password';
            setVisible(input, btn, show);
            try {
                input.focus({ preventScroll: true });
            } catch (_) {
                input.focus();
            }
        });

        wrap.appendChild(btn);
    }

    function scan(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var nodes = scope.querySelectorAll('input[type="password"]');
        for (var i = 0; i < nodes.length; i++) {
            enhance(nodes[i]);
        }
    }

    function init() {
        scan(document);
        if (typeof MutationObserver === 'undefined') return;
        var obs = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var m = mutations[i];
                if (m.type === 'childList') {
                    for (var j = 0; j < m.addedNodes.length; j++) {
                        var n = m.addedNodes[j];
                        if (n.nodeType !== 1) continue;
                        if (n.matches && n.matches('input[type="password"]')) enhance(n);
                        else if (n.querySelectorAll) scan(n);
                    }
                } else if (m.type === 'attributes' && m.target && m.target.matches) {
                    if (m.attributeName === 'type' && m.target.matches('input[type="password"]')) {
                        enhance(m.target);
                    }
                }
            }
        });
        obs.observe(document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['type'],
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    global.PosPasswordToggle = { enhance: enhance, scan: scan };
})(window);

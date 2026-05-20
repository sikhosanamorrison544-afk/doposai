/**
 * Web/desktop thermal printer preferences (localStorage).
 * USB via WebUSB; Bluetooth via Web Serial (paired BT SPP COM port).
 */
(function (global) {
    'use strict';

    const STORAGE_KEY = 'pos_web_printer_v1';

    const defaults = {
        preference: 'auto',
        paperWidth: 32,
    };

    function load() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return Object.assign({}, defaults);
            const parsed = JSON.parse(raw);
            return Object.assign({}, defaults, parsed);
        } catch (e) {
            return Object.assign({}, defaults);
        }
    }

    function save(patch) {
        const next = Object.assign(load(), patch || {});
        if (next.preference !== 'auto' && next.preference !== 'usb' && next.preference !== 'bluetooth') {
            next.preference = 'auto';
        }
        next.paperWidth = next.paperWidth === 48 ? 48 : 32;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        return next;
    }

    function getPreference() {
        return load().preference;
    }

    function setPreference(value) {
        return save({ preference: value });
    }

    function getPaperWidth() {
        return load().paperWidth;
    }

    function setPaperWidth(width) {
        return save({ paperWidth: width === 48 ? 48 : 32 });
    }

    global.posWebPrinterPrefs = {
        load: load,
        save: save,
        getPreference: getPreference,
        setPreference: setPreference,
        getPaperWidth: getPaperWidth,
        setPaperWidth: setPaperWidth,
    };
})(typeof window !== 'undefined' ? window : global);

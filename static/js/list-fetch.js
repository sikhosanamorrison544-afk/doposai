/**
 * Fetch full product/customer lists via paginated API (avoids 502 on large tenants).
 */
(function (global) {
    'use strict';

    const PAGE_SIZE = 500;
    const MAX_ROWS = 20000;

    function isListCollectionPath(path) {
        const base = String(path || '').split('?')[0];
        return base === '/api/products' || base === '/api/customers';
    }

    /**
     * @param {string} path - e.g. /api/products
     * @param {object} options - { headers, credentials, pageSize }
     */
    async function fetchAllListPages(path, options) {
        const opts = options || {};
        const pageSize = opts.pageSize || PAGE_SIZE;
        const headers = { ...(opts.headers || {}) };
        const credentials = opts.credentials || 'same-origin';
        const all = [];
        let offset = 0;
        let total = null;

        while (offset < MAX_ROWS) {
            const sep = path.includes('?') ? '&' : '?';
            const url = `${path}${sep}limit=${pageSize}&offset=${offset}`;
            const res = await fetch(url, { method: 'GET', headers, credentials });
            if (!res.ok) {
                const text = await res.text();
                const err = new Error(text || res.statusText);
                err.status = res.status;
                throw err;
            }
            if (total === null) {
                const h = res.headers.get('X-Total-Count');
                if (h) {
                    const n = parseInt(h, 10);
                    if (!Number.isNaN(n)) total = n;
                }
            }
            const batch = await res.json();
            if (!Array.isArray(batch) || batch.length === 0) break;
            all.push(...batch);
            offset += batch.length;
            if (batch.length < pageSize) break;
            if (total !== null && offset >= total) break;
        }
        return all;
    }

    global.posIsListCollectionPath = isListCollectionPath;
    global.posFetchAllListPages = fetchAllListPages;
})(typeof window !== 'undefined' ? window : globalThis);

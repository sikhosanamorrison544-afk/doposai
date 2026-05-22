/**
 * DoposAI Business Intelligence — health scores & advisor API
 */
(function () {
    'use strict';

    const METRICS = [
        { key: 'business_health', dot: 'bi-dot-business', val: 'bi-val-business', score: 'business_health_score' },
        { key: 'sales_trend', dot: 'bi-dot-sales', val: 'bi-val-sales', score: 'sales_trend_score' },
        { key: 'inventory_risk', dot: 'bi-dot-inventory', val: 'bi-val-inventory', score: 'inventory_risk_score' },
        { key: 'profitability', dot: 'bi-dot-profit', val: 'bi-val-profit', score: 'profitability_score' },
    ];

    function getDays() {
        const sel = document.getElementById('period-select');
        return sel ? parseInt(sel.value, 10) || 30 : 30;
    }

    function biApi(path, options) {
        if (typeof analyticsApi === 'function') {
            return analyticsApi(path, options);
        }
        throw new Error('analyticsApi not available');
    }

    function applyHealthScores(data) {
        const hs = data && data.health_scores;
        if (!hs) return;
        METRICS.forEach(function (m) {
            const dot = document.getElementById(m.dot);
            const val = document.getElementById(m.val);
            const color = hs[m.key] || 'yellow';
            const score = hs[m.score];
            if (dot) {
                dot.className = 'bi-score-dot ' + color;
            }
            if (val) {
                val.textContent = typeof score === 'number' ? Math.round(score) + '/100' : '—';
            }
        });
    }

    function renderAdvisorResponse(res) {
        const s = res.structured || {};
        let html = '<h3>' + escapeHtml(s.summary || res.narrative || 'Analysis') + '</h3>';
        function list(title, items) {
            if (!items || !items.length) return '';
            return (
                '<h3>' +
                title +
                '</h3><ul>' +
                items.map(function (i) {
                    return '<li>' + escapeHtml(String(i)) + '</li>';
                }).join('') +
                '</ul>'
            );
        }
        html += list('Insights', s.insights);
        html += list('Risks', s.risks);
        html += list('Recommendations', s.recommendations);
        html += list('Action plan', s.action_plan);
        if (res.cached) {
            html += '<p style="font-size:12px;opacity:0.7;">Cached response</p>';
        }
        return html;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    async function loadHealthScores() {
        const section = document.getElementById('bi-health-section');
        const status = document.getElementById('bi-status-line');
        if (!section) return;
        try {
            const days = getDays();
            const data = await biApi('/api/bi/health-scores?days=' + days);
            section.style.display = 'block';
            applyHealthScores(data);
            const st = await biApi('/api/bi/status').catch(function () {
                return { ai_service_configured: false };
            });
            if (status) {
                status.textContent = st.ai_service_configured
                    ? 'Qwen3 advisor connected · scores based on your store data'
                    : 'Analytics active · configure AI_SERVICE_URL on server for full Qwen3 advice';
            }
        } catch (e) {
            if (status) status.textContent = 'BI unavailable: ' + (e.message || e);
            console.warn('BI health scores:', e);
        }
    }

    async function runAnalysis(endpoint, label) {
        const out = document.getElementById('bi-advisor-output');
        if (!out) return;
        out.style.display = 'block';
        out.innerHTML = '<p>Loading ' + escapeHtml(label) + '…</p>';
        try {
            const days = getDays();
            const res = await biApi('/api/bi/' + endpoint + '?days=' + days, { method: 'POST' });
            out.innerHTML = renderAdvisorResponse(res);
        } catch (e) {
            out.innerHTML = '<p class="error">' + escapeHtml(e.message || String(e)) + '</p>';
        }
    }

    async function askAdvisor() {
        const q = window.prompt('Ask DoposAI Business Advisor:', 'What should I restock next week?');
        if (!q || !q.trim()) return;
        const out = document.getElementById('bi-advisor-output');
        if (!out) return;
        out.style.display = 'block';
        out.innerHTML = '<p>Thinking…</p>';
        try {
            const res = await biApi('/api/bi/ask', {
                method: 'POST',
                body: JSON.stringify({ question: q.trim(), days: getDays() }),
            });
            out.innerHTML =
                '<p><strong>Intent:</strong> ' +
                escapeHtml(res.detected_intent || '') +
                '</p>' +
                renderAdvisorResponse(res);
        } catch (e) {
            out.innerHTML = '<p class="error">' + escapeHtml(e.message || String(e)) + '</p>';
        }
    }

    function wireButtons() {
        const map = [
            ['btn-bi-insights', 'business-insights', 'business insights'],
            ['btn-bi-sales', 'sales-analysis', 'sales analysis'],
            ['btn-bi-inventory', 'inventory-analysis', 'inventory analysis'],
        ];
        map.forEach(function (item) {
            const btn = document.getElementById(item[0]);
            if (btn) {
                btn.addEventListener('click', function () {
                    runAnalysis(item[1], item[2]);
                });
            }
        });
        const ask = document.getElementById('btn-bi-ask');
        if (ask) ask.addEventListener('click', askAdvisor);
    }

    document.addEventListener('DOMContentLoaded', function () {
        wireButtons();
        loadHealthScores();
        const period = document.getElementById('period-select');
        if (period) {
            period.addEventListener('change', loadHealthScores);
        }
    });

    window.loadBIHealthScores = loadHealthScores;
})();

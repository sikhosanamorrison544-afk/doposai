let withdrawalsToken = null;
let withdrawalsUser = null;
let allWithdrawals = [];

// Helper function to escape HTML
function escapeHtml(text) {
    if (text == null || text === '') return '-';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Check authentication
async function ensureAuthenticated() {
    const savedToken = localStorage.getItem('pos_token');
    const savedUser = localStorage.getItem('pos_user');
    if (savedToken && savedUser) {
        withdrawalsToken = savedToken.trim();
        withdrawalsUser = JSON.parse(savedUser);
        const userInfoEl = document.getElementById('withdrawals-user-info');
        if (userInfoEl) {
            userInfoEl.textContent = `${withdrawalsUser.username} (${withdrawalsUser.role})`;
        }
        return true;
    }
    window.location.href = '/';
    return false;
}

async function withdrawalsApi(path, options = {}) {
    const savedToken = localStorage.getItem('pos_token');
    if (savedToken && savedToken.trim()) {
        withdrawalsToken = savedToken.trim();
    }
    
    if (!withdrawalsToken || !withdrawalsToken.trim()) {
        const authenticated = await ensureAuthenticated();
        if (!authenticated) {
            throw new Error('Not authenticated. Please refresh the page and login again.');
        }
        const retryToken = localStorage.getItem('pos_token');
        if (retryToken && retryToken.trim()) {
            withdrawalsToken = retryToken.trim();
        }
    }
    
    if (!withdrawalsToken || !withdrawalsToken.trim()) {
        throw new Error('Not authenticated. Please refresh the page and login again.');
    }
    
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    headers['Authorization'] = 'Bearer ' + withdrawalsToken.trim();
    
    const res = await fetch(path, {
        ...options,
        headers,
    });
    
    if (!res.ok) {
        const text = await res.text();
        let errorMsg = text;
        try {
            const errorJson = JSON.parse(text);
            errorMsg = errorJson.detail || errorJson.message || text;
        } catch (e) {
            // Not JSON, use text as is
        }
        
        if (res.status === 401) {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
            return;
        }
        
        throw new Error(errorMsg || res.statusText);
    }
    
    if (res.status === 204) return null;
    return res.json();
}

// Load withdrawals
async function loadWithdrawals() {
    const body = document.getElementById('withdrawals-body');
    const msg = document.getElementById('withdrawals-message');
    
    if (!body) {
        console.error('Withdrawals body element not found');
        return;
    }
    
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:#ffffff;">Loading withdrawals...</td></tr>';
    if (msg) {
        msg.style.display = 'none';
        msg.textContent = '';
    }
    
    try {
        allWithdrawals = await withdrawalsApi('/api/withdrawals?limit=1000');
        console.log(`Loaded ${allWithdrawals.length} withdrawals`);
        filterAndRenderWithdrawals();
    } catch (e) {
        console.error('Error loading withdrawals:', e);
        const errorMsg = e.message || 'Unknown error';
        body.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:40px;color:rgba(239, 68, 68, 1);">Error loading withdrawals: ${errorMsg}</td></tr>`;
        if (msg) {
            msg.textContent = `Failed to load withdrawals: ${errorMsg}`;
            msg.style.color = 'rgba(239, 68, 68, 1)';
            msg.style.background = 'rgba(239, 68, 68, 0.2)';
            msg.style.display = 'block';
        }
    }
}

function filterAndRenderWithdrawals() {
    const body = document.getElementById('withdrawals-body');
    const reasonFilterEl = document.getElementById('withdrawal-filter-reason');
    const searchEl = document.getElementById('withdrawal-search');
    
    if (!body) return;
    
    const reasonFilter = reasonFilterEl ? reasonFilterEl.value : '';
    const searchTerm = searchEl ? searchEl.value.toLowerCase() : '';
    
    let filtered = allWithdrawals;
    
    // Filter by reason
    if (reasonFilter) {
        filtered = filtered.filter(w => w.reason === reasonFilter);
    }
    
    // Filter by search term
    if (searchTerm) {
        filtered = filtered.filter(w => 
            (w.cashier_name && w.cashier_name.toLowerCase().includes(searchTerm)) ||
            (w.receipt_number && w.receipt_number.toLowerCase().includes(searchTerm)) ||
            (w.notes && w.notes.toLowerCase().includes(searchTerm))
        );
    }
    
    // Sort by date (newest first)
    filtered.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    
    // Render table
    body.innerHTML = '';
    
    if (filtered.length === 0) {
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:rgba(255,255,255,0.5);">No withdrawals found</td></tr>';
        updateWithdrawalTotals([]);
        return;
    }
    
    filtered.forEach((w, index) => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid rgba(255, 255, 255, 0.1)';
        const date = new Date(w.created_at);
        const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        
        // Determine reason badge color
        let reasonBadgeColor = 'rgba(107, 114, 128, 0.3)';
        let reasonTextColor = '#9ca3af';
        if (w.reason === 'Daily expenses') {
            reasonBadgeColor = 'rgba(245, 158, 11, 0.3)';
            reasonTextColor = '#f59e0b';
        } else if (w.reason === 'Buying company assets') {
            reasonBadgeColor = 'rgba(59, 130, 246, 0.3)';
            reasonTextColor = '#3b82f6';
        }
        
        tr.innerHTML = `
            <td style="text-align: center; padding: 12px;">${index + 1}</td>
            <td style="padding: 12px;">${escapeHtml(dateStr)}</td>
            <td style="padding: 12px; font-weight: bold;">${escapeHtml(w.receipt_number || 'N/A')}</td>
            <td style="padding: 12px; text-align: right; font-weight: bold; color: rgba(239, 68, 68, 1);">$${parseFloat(w.amount).toFixed(2)}</td>
            <td style="padding: 12px;">
                <span style="padding: 4px 8px; border-radius: 4px; background: ${reasonBadgeColor}; color: ${reasonTextColor};">
                    ${escapeHtml(w.reason)}
                </span>
            </td>
            <td style="padding: 12px;">${escapeHtml(w.cashier_name || 'Unknown')}</td>
            <td style="padding: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(w.notes || '')}">${escapeHtml(w.notes || '-')}</td>
        `;
        body.appendChild(tr);
    });
    
    updateWithdrawalTotals(filtered);
    if (typeof window.renderWithdrawalsMobile === 'function') {
        window.renderWithdrawalsMobile(filtered);
    }
}


function updateWithdrawalTotals(withdrawals) {
    const totalCount = withdrawals.length;
    const totalAmount = withdrawals.reduce((sum, w) => sum + parseFloat(w.amount || 0), 0);
    const expensesTotal = withdrawals
        .filter(w => w.reason === 'Daily expenses')
        .reduce((sum, w) => sum + parseFloat(w.amount || 0), 0);
    const assetsTotal = withdrawals
        .filter(w => w.reason === 'Buying company assets')
        .reduce((sum, w) => sum + parseFloat(w.amount || 0), 0);
    
    const countEl = document.getElementById('withdrawal-total-count');
    const amountEl = document.getElementById('withdrawal-total-amount');
    const expensesEl = document.getElementById('withdrawal-expenses-total');
    const assetsEl = document.getElementById('withdrawal-assets-total');
    
    if (countEl) countEl.textContent = totalCount;
    if (amountEl) amountEl.textContent = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(totalAmount);
    if (expensesEl) expensesEl.textContent = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(expensesTotal);
    if (assetsEl) assetsEl.textContent = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(assetsTotal);
}

async function syncWithdrawalsToBackup() {
    const msg = document.getElementById('withdrawals-message');
    const btn = document.getElementById('btn-sync-withdrawals-backup');
    
    if (msg) {
        msg.textContent = 'Syncing to Google Sheets...';
        msg.style.color = '#ffffff';
        msg.style.background = 'rgba(59, 130, 246, 0.2)';
        msg.style.display = 'block';
    }
    
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Syncing...';
    }
    
    try {
        const result = await withdrawalsApi('/api/backup/sync-withdrawals', {
            method: 'POST'
        });
        
        if (msg) {
            if (result.success) {
                msg.textContent = result.message || 'Withdrawals synced successfully';
                msg.style.color = 'rgba(34, 197, 94, 1)';
                msg.style.background = 'rgba(34, 197, 94, 0.2)';
            } else {
                msg.textContent = result.message || 'Sync failed';
                msg.style.color = 'rgba(239, 68, 68, 1)';
                msg.style.background = 'rgba(239, 68, 68, 0.2)';
            }
        }
    } catch (e) {
        console.error('Error syncing withdrawals:', e);
        if (msg) {
            msg.textContent = 'Sync failed: ' + (e.message || 'Unknown error');
            msg.style.color = 'rgba(239, 68, 68, 1)';
            msg.style.background = 'rgba(239, 68, 68, 0.2)';
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '🔄 Sync to Google Sheets';
        }
    }
}

// Theme management
function applyTheme(themeName) {
    const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
    document.body.classList.remove(...themeClasses);
    document.documentElement.classList.remove(...themeClasses);
    
    const theme = ['default', 'light', 'classic'].includes(themeName) ? themeName : 'default';
    const cls = 'theme-' + theme;
    document.body.classList.add(cls);
    document.documentElement.classList.add(cls);
    
    if (themeName === 'light') {
        if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
    } else if (typeof window.hideLightThemeVideo === 'function') {
        window.hideLightThemeVideo();
    }
    
    // Save to localStorage
    localStorage.setItem('pos-theme', themeName || 'default');
    
    // Update active button
    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.theme === (themeName || 'default')) {
            btn.classList.add('active');
        }
    });
}

function loadTheme() {
    const savedTheme = localStorage.getItem('pos-theme') || 'default';
    applyTheme(savedTheme);
    
    // Ensure video plays if light theme is already active
    if (savedTheme === 'light') {
        setTimeout(() => {
            if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
        }, 100);
    }
}

// Setup event handlers
document.addEventListener('DOMContentLoaded', async () => {
    await ensureAuthenticated();
    
    // Load saved theme
    loadTheme();
    
    // Back to admin button
    const backBtn = document.getElementById('btn-back-to-admin');
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            window.location.href = '/admin';
        });
    }
    
    // Logout button
    const logoutBtn = document.getElementById('btn-withdrawals-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
        });
    }
    
    // Sync button
    const syncBtn = document.getElementById('btn-sync-withdrawals-backup');
    if (syncBtn) {
        syncBtn.addEventListener('click', syncWithdrawalsToBackup);
    }
    
    // Filter and search handlers
    const reasonFilter = document.getElementById('withdrawal-filter-reason');
    const searchInput = document.getElementById('withdrawal-search');
    
    if (reasonFilter) {
        reasonFilter.addEventListener('change', filterAndRenderWithdrawals);
    }
    if (searchInput) {
        searchInput.addEventListener('input', filterAndRenderWithdrawals);
    }
    
    if (typeof window.initWithdrawalsPageUi === 'function') {
        window.initWithdrawalsPageUi();
    }

    // Load withdrawals
    await loadWithdrawals();
});


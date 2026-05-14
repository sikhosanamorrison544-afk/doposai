let debtsToken = null;
let debtsUser = null;

// Theme management
function applyTheme(themeName) {
    // Remove all theme classes from both html and body
    const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
    document.documentElement.classList.remove(...themeClasses);
    document.body.classList.remove(...themeClasses);
    
    // Add selected theme class to both html and body
    if (themeName && themeName !== 'default') {
        const themeClass = 'theme-' + themeName;
        document.documentElement.classList.add(themeClass);
        document.body.classList.add(themeClass);
    }
    
    // Handle 3D background canvas (only for default theme)
    const canvas = document.getElementById('bg3d-canvas');
    if (canvas) {
        if (themeName === 'default' || !themeName) {
            // Show 3D canvas for default theme
            canvas.style.display = 'block';
        } else {
            // Hide 3D canvas for other themes
            canvas.style.display = 'none';
        }
    }
    
    // Handle video background for light theme
    const video = document.getElementById('light-theme-video');
    if (video) {
        if (themeName === 'light') {
            video.style.display = 'block';
            video.play().catch(err => {
                console.log('Video autoplay prevented:', err);
            });
        } else {
            video.style.display = 'none';
            video.pause();
        }
    }
    
    // Apply light theme styling to outstanding debts page elements
    if (themeName === 'light') {
        applyLightThemeStyles();
    }
}

// Function to apply light theme styles to outstanding debts page elements
function applyLightThemeStyles() {
    // Override Grand Total Outstanding panel inline styles - find by containing grand-total element
    const grandTotalEl = document.getElementById('grand-total');
    if (grandTotalEl && grandTotalEl.parentElement && grandTotalEl.parentElement.parentElement) {
        const grandTotalPanel = grandTotalEl.parentElement.parentElement;
        if (grandTotalPanel && grandTotalPanel.tagName === 'DIV') {
            grandTotalPanel.style.setProperty('background', 'rgba(239, 68, 68, 0.2)', 'important');
            grandTotalPanel.style.setProperty('backdrop-filter', 'blur(20px) saturate(180%)', 'important');
            grandTotalPanel.style.setProperty('-webkit-backdrop-filter', 'blur(20px) saturate(180%)', 'important');
            grandTotalPanel.style.setProperty('border', '2px solid rgba(239, 68, 68, 0.4)', 'important');
            grandTotalPanel.style.setProperty('box-shadow', '0 8px 32px rgba(0, 0, 0, 0.1)', 'important');
        }
    }
    
    // Override table container inline styles
    const tableContainer = document.getElementById('debts-table-container');
    if (tableContainer) {
        tableContainer.style.setProperty('background', 'rgba(255, 255, 255, 0.1)', 'important');
        tableContainer.style.setProperty('backdrop-filter', 'blur(20px) saturate(180%)', 'important');
        tableContainer.style.setProperty('-webkit-backdrop-filter', 'blur(20px) saturate(180%)', 'important');
        tableContainer.style.setProperty('border', '1px solid rgba(255, 255, 255, 0.2)', 'important');
        tableContainer.style.setProperty('box-shadow', '0 8px 32px rgba(0, 0, 0, 0.1)', 'important');
    }
}

function loadTheme() {
    const savedTheme = localStorage.getItem('pos-theme') || 'default';
    applyTheme(savedTheme);
    
    // Ensure video plays if light theme is already active
    if (savedTheme === 'light') {
        setTimeout(() => {
            const video = document.getElementById('light-theme-video');
            if (video && video.paused) {
                video.play().catch(err => {
                    console.log('Video autoplay on load prevented:', err);
                });
            }
        }, 100);
    }
    
    // Force 3D background to update based on theme
    setTimeout(() => {
        const canvas = document.getElementById('bg3d-canvas');
        if (canvas) {
            if (savedTheme === 'default' || !savedTheme) {
                // Default theme - show 3D canvas
                canvas.style.display = 'block';
            } else {
                // Other themes - hide 3D canvas
                canvas.style.display = 'none';
            }
        }
        
        // Trigger background3d.js theme check if available
        if (typeof window.checkTheme === 'function') {
            window.checkTheme();
        }
    }, 200);
}

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
        debtsToken = savedToken.trim();
        debtsUser = JSON.parse(savedUser);
        const userInfoEl = document.getElementById('debts-user-info');
        if (userInfoEl) {
            userInfoEl.textContent = `${debtsUser.username} (${debtsUser.role})`;
        }
        return true;
    }
    window.location.href = '/';
    return false;
}

async function debtsApi(path, options = {}) {
    const savedToken = localStorage.getItem('pos_token');
    if (savedToken && savedToken.trim()) {
        debtsToken = savedToken.trim();
    }
    
    if (!debtsToken || !debtsToken.trim()) {
        const authenticated = await ensureAuthenticated();
        if (!authenticated) {
            throw new Error('Not authenticated. Please refresh the page and login again.');
        }
        const retryToken = localStorage.getItem('pos_token');
        if (retryToken && retryToken.trim()) {
            debtsToken = retryToken.trim();
        }
    }
    
    if (!debtsToken || !debtsToken.trim()) {
        throw new Error('Not authenticated. Please refresh the page and login again.');
    }
    
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    headers['Authorization'] = 'Bearer ' + debtsToken.trim();
    
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

// Load outstanding debts
async function loadOutstandingDebts() {
    try {
        const data = await debtsApi('/api/debts/outstanding');
        
        // Check if default theme or light theme (no theme class on body = default)
        const isDefaultTheme = !document.body.classList.toString().match(/theme-/);
        const isLightTheme = document.body.classList.contains('theme-light');
        // Set white color for all text in default theme and light theme
        const textColor = (isDefaultTheme || isLightTheme) ? 'color: #ffffff !important;' : '';
        
        // Update count
        const countEl = document.getElementById('debts-count');
        if (countEl) {
            countEl.textContent = `(${data.count} customer${data.count !== 1 ? 's' : ''})`;
            // Ensure white color in default theme and light theme
            if (isDefaultTheme || isLightTheme) {
                countEl.style.color = '#ffffff';
            }
        }
        
        // Update grand total
        const grandTotalEl = document.getElementById('grand-total');
        if (grandTotalEl) {
            grandTotalEl.textContent = `$${parseFloat(data.grand_total).toFixed(2)}`;
            // Keep red color for grand total (it's not black text, so it should stay red)
            // Only ensure black text becomes white
        }
        
        // Render table
        const tbody = document.getElementById('debts-body');
        if (!tbody) return;
        
        tbody.innerHTML = '';
        
        if (data.debts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ffffff;">No outstanding debts found.</td></tr>';
            // Apply light theme styles after rendering
            setTimeout(applyLightThemeStyles, 50);
            return;
        }
        
        data.debts.forEach((debt, index) => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid rgba(255, 255, 255, 0.1)';
            tr.innerHTML = `
                <td style="text-align: center; padding: 12px; ${textColor}">${index + 1}</td>
                <td style="padding: 12px; font-weight: bold; ${textColor}">${escapeHtml(debt.customer_name)}</td>
                <td style="padding: 12px; ${textColor}">${escapeHtml(debt.phone)}</td>
                <td style="padding: 12px; ${textColor}">${escapeHtml(debt.address)}</td>
                <td style="padding: 12px; text-align: center;">
                    <span style="padding: 4px 8px; border-radius: 4px; background: ${debt.debt_type === 'layby' ? 'rgba(59, 130, 246, 0.3)' : 'rgba(245, 158, 11, 0.3)'}; color: ${debt.debt_type === 'layby' ? '#60a5fa' : '#fbbf24'};">
                        ${debt.debt_type === 'layby' ? 'Layby' : 'Credit Sale'}
                    </span>
                </td>
                <td style="padding: 12px; text-align: right; font-weight: bold; color: #ffffff !important;">
                    $${parseFloat(debt.debt_amount).toFixed(2)}
                </td>
            `;
            tbody.appendChild(tr);
        });
        
        // Apply light theme styles after rendering
        setTimeout(applyLightThemeStyles, 50);
        
    } catch (e) {
        console.error('Error loading outstanding debts:', e);
        const tbody = document.getElementById('debts-body');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ef4444;">Error loading debts: ${e.message}</td></tr>`;
        }
    }
}

// Setup event handlers
document.addEventListener('DOMContentLoaded', async () => {
    // Load theme first
    loadTheme();
    
    // Apply light theme styles if light theme is active
    const savedTheme = localStorage.getItem('pos-theme') || 'default';
    if (savedTheme === 'light') {
        setTimeout(applyLightThemeStyles, 100);
    }
    
    // Listen for theme changes from other tabs/windows
    window.addEventListener('storage', (e) => {
        if (e.key === 'pos-theme') {
            loadTheme();
            const newTheme = localStorage.getItem('pos-theme') || 'default';
            if (newTheme === 'light') {
                setTimeout(applyLightThemeStyles, 100);
            }
        }
    });
    
    // Also check for theme changes periodically (in case storage event doesn't fire)
    setInterval(() => {
        const currentTheme = localStorage.getItem('pos-theme') || 'default';
        const bodyTheme = Array.from(document.body.classList).find(c => c.startsWith('theme-'));
        const expectedTheme = currentTheme === 'default' ? null : 'theme-' + currentTheme;
        if (bodyTheme !== expectedTheme) {
            loadTheme();
            if (currentTheme === 'light') {
                setTimeout(applyLightThemeStyles, 100);
            }
        }
    }, 500);
    
    await ensureAuthenticated();
    
    // Back to layby button
    const backBtn = document.getElementById('btn-back-to-layby');
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            window.location.href = '/layby';
        });
    }
    
    // Logout button
    const logoutBtn = document.getElementById('btn-debts-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
        });
    }
    
    // Load debts
    await loadOutstandingDebts();
});


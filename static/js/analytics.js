let analyticsToken = null;
let analyticsUser = null;

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
        analyticsToken = savedToken.trim();
        analyticsUser = JSON.parse(savedUser);
        const userInfoEl = document.getElementById('analytics-user-info');
        if (userInfoEl) {
            userInfoEl.textContent = `${analyticsUser.username} (${analyticsUser.role})`;
        }
        return true;
    }
    window.location.href = '/';
    return false;
}

async function analyticsApi(path, options = {}) {
    const savedToken = localStorage.getItem('pos_token');
    if (savedToken && savedToken.trim()) {
        analyticsToken = savedToken.trim();
    }
    
    if (!analyticsToken || !analyticsToken.trim()) {
        const authenticated = await ensureAuthenticated();
        if (!authenticated) {
            throw new Error('Not authenticated. Please refresh the page and login again.');
        }
        const retryToken = localStorage.getItem('pos_token');
        if (retryToken && retryToken.trim()) {
            analyticsToken = retryToken.trim();
        }
    }
    
    if (!analyticsToken || !analyticsToken.trim()) {
        throw new Error('Not authenticated. Please refresh the page and login again.');
    }
    
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    headers['Authorization'] = 'Bearer ' + analyticsToken.trim();
    
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

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

function formatNumber(num) {
    return new Intl.NumberFormat('en-US').format(num);
}

async function loadDashboard(days = 30) {
    try {
        const data = await analyticsApi(`/api/analytics/dashboard?days=${days}`);
        
        // Update summary stats
        const topProduct = data.top_selling;
        const leastProduct = data.least_selling;
        const summary = data.summary;
        
        // Top selling product
        const topProductNameEl = document.getElementById('top-product-name');
        const topProductStatsEl = document.getElementById('top-product-stats');
        if (topProductNameEl && topProductStatsEl) {
            if (topProduct.product_name) {
                topProductNameEl.textContent = escapeHtml(topProduct.product_name);
                topProductStatsEl.innerHTML = `
                    <div>Quantity: ${formatNumber(topProduct.quantity_sold)}</div>
                    <div>Revenue: ${formatCurrency(topProduct.revenue)}</div>
                    ${topProduct.barcode ? `<div style="font-size: 11px; color: rgba(255,255,255,0.4);">Barcode: ${escapeHtml(topProduct.barcode)}</div>` : ''}
                `;
            } else {
                topProductNameEl.textContent = 'No sales data';
                topProductStatsEl.textContent = 'No products sold in this period';
            }
        }
        
        // Least selling product
        const leastProductNameEl = document.getElementById('least-product-name');
        const leastProductStatsEl = document.getElementById('least-product-stats');
        if (leastProductNameEl && leastProductStatsEl) {
            if (leastProduct.product_name) {
                leastProductNameEl.textContent = escapeHtml(leastProduct.product_name);
                leastProductStatsEl.innerHTML = `
                    <div>Quantity: ${formatNumber(leastProduct.quantity_sold)}</div>
                    <div>Revenue: ${formatCurrency(leastProduct.revenue)}</div>
                    ${leastProduct.barcode ? `<div style="font-size: 11px; color: rgba(255,255,255,0.4);">Barcode: ${escapeHtml(leastProduct.barcode)}</div>` : ''}
                `;
            } else {
                leastProductNameEl.textContent = 'No sales data';
                leastProductStatsEl.textContent = 'No products sold in this period';
            }
        }
        
        // Total revenue
        const totalRevenueEl = document.getElementById('total-revenue');
        const revenueLabelEl = document.getElementById('revenue-label');
        if (totalRevenueEl) {
            totalRevenueEl.textContent = formatCurrency(summary.total_revenue);
        }
        if (revenueLabelEl) {
            revenueLabelEl.textContent = `${summary.total_products_sold} products sold`;
        }
        
        // Zero sales count
        const zeroSalesCountEl = document.getElementById('zero-sales-count');
        if (zeroSalesCountEl) {
            zeroSalesCountEl.textContent = formatNumber(summary.zero_sales_count);
        }
        
    } catch (e) {
        console.error('Error loading dashboard:', e);
        showError('Failed to load dashboard: ' + e.message);
    }
}

async function loadRevenuePerProduct(days = 30) {
    const container = document.getElementById('revenue-table-container');
    if (!container) return;
    
    try {
        container.innerHTML = '<div class="loading">Loading revenue data...</div>';
        
        const data = await analyticsApi(`/api/analytics/revenue-per-product?days=${days}&limit=20`);
        
        if (data.length === 0) {
            container.innerHTML = '<div class="loading">No sales data available for this period</div>';
            return;
        }
        
        let html = `
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Product Name</th>
                        <th>Barcode</th>
                        <th style="text-align: right;">Quantity Sold</th>
                        <th style="text-align: right;">Revenue</th>
                        <th style="text-align: right;">Profit</th>
                        <th style="text-align: center;">Sales Count</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        data.forEach((product, index) => {
            html += `
                <tr>
                    <td style="color: #ffffff;">${index + 1}</td>
                    <td style="color: #ffffff;">${escapeHtml(product.product_name)}</td>
                    <td style="color: #ffffff;">${product.barcode ? escapeHtml(product.barcode) : '<span class="badge warning">No barcode</span>'}</td>
                    <td style="text-align: right; color: #ffffff;">${formatNumber(product.total_quantity_sold)}</td>
                    <td style="text-align: right; font-weight: bold; color: #10b981;">${formatCurrency(parseFloat(product.total_revenue))}</td>
                    <td style="text-align: right; color: #3b82f6;">${formatCurrency(parseFloat(product.total_profit))}</td>
                    <td style="text-align: center; color: #ffffff;">${formatNumber(product.sale_count)}</td>
                </tr>
            `;
        });
        
        html += `
                </tbody>
            </table>
        `;
        
        container.innerHTML = html;
    } catch (e) {
        console.error('Error loading revenue per product:', e);
        container.innerHTML = `<div class="error">Failed to load revenue data: ${e.message}</div>`;
    }
}

async function loadZeroSalesProducts(days = 30) {
    const container = document.getElementById('zero-sales-table-container');
    if (!container) return;
    
    try {
        container.innerHTML = '<div class="loading">Loading zero sales products...</div>';
        
        const data = await analyticsApi(`/api/analytics/zero-sales?days=${days}`);
        
        if (data.length === 0) {
            container.innerHTML = '<div class="loading">All products have sales in this period! 🎉</div>';
            return;
        }
        
        let html = `
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Product Name</th>
                        <th>Barcode</th>
                        <th style="text-align: right;">Stock Qty</th>
                        <th style="text-align: right;">Selling Price</th>
                        <th>Last Sale Date</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        data.forEach((product, index) => {
            const lastSaleDate = product.last_sale_date 
                ? new Date(product.last_sale_date).toLocaleDateString()
                : '<span class="badge danger">Never sold</span>';
            
            html += `
                <tr>
                    <td style="color: #ffffff;">${index + 1}</td>
                    <td style="color: #ffffff;">${escapeHtml(product.product_name)}</td>
                    <td style="color: #ffffff;">${product.barcode ? escapeHtml(product.barcode) : '<span class="badge warning">No barcode</span>'}</td>
                    <td style="text-align: right; color: #ffffff;">${formatNumber(product.stock_qty)}</td>
                    <td style="text-align: right; color: #ffffff;">${formatCurrency(parseFloat(product.selling_price))}</td>
                    <td style="color: #ffffff;">${lastSaleDate}</td>
                </tr>
            `;
        });
        
        html += `
                </tbody>
            </table>
        `;
        
        container.innerHTML = html;
    } catch (e) {
        console.error('Error loading zero sales products:', e);
        container.innerHTML = `<div class="error">Failed to load zero sales products: ${e.message}</div>`;
    }
}

function showError(message) {
    const errorEl = document.getElementById('error-message');
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.style.display = 'block';
        setTimeout(() => {
            errorEl.style.display = 'none';
        }, 5000);
    }
}

async function refreshAll(days) {
    const tasks = [loadDashboard(days), loadZeroSalesProducts(days)];
    if (typeof window.isPosAndroidApp === 'function' && window.isPosAndroidApp()) {
        const revenueEl = document.getElementById('revenue-table-container');
        if (revenueEl) revenueEl.innerHTML = '';
    } else {
        tasks.push(loadRevenuePerProduct(days));
    }
    await Promise.all(tasks);
}

// Theme management
function applyTheme(themeName) {
    // Remove all theme classes from both body and html elements
    const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
    document.body.classList.remove(...themeClasses);
    document.documentElement.classList.remove(...themeClasses);
    
    // Add selected theme class to both body and html elements
    if (themeName && themeName !== 'default') {
        const themeClass = 'theme-' + themeName;
        document.body.classList.add(themeClass);
        document.documentElement.classList.add(themeClass);
    }
    
    // Handle video background for light theme
    const video = document.getElementById('light-theme-video');
    if (video) {
        if (themeName === 'light') {
            video.style.display = 'block';
            video.play().catch(err => {
                console.log('Video autoplay prevented:', err);
                // If autoplay fails, try again after user interaction
                document.addEventListener('click', function playVideoOnce() {
                    video.play().catch(() => {});
                    document.removeEventListener('click', playVideoOnce);
                }, { once: true });
            });
        } else {
            video.style.display = 'none';
            video.pause();
        }
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
            const video = document.getElementById('light-theme-video');
            if (video && video.paused) {
                video.play().catch(err => {
                    console.log('Video autoplay on load prevented:', err);
                });
            }
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
    const logoutBtn = document.getElementById('btn-analytics-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
        });
    }
    
    // Period selector
    const periodSelect = document.getElementById('period-select');
    if (periodSelect) {
        periodSelect.addEventListener('change', async (e) => {
            const days = parseInt(e.target.value);
            await refreshAll(days);
        });
    }
    
    if (typeof window.initAnalyticsPageUi === 'function') {
        window.initAnalyticsPageUi();
    }

    // Load initial data
    const initialDays = periodSelect ? parseInt(periodSelect.value) : 30;
    await refreshAll(initialDays);
});


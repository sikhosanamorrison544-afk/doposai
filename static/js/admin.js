let adminToken = null;
let adminUser = null;
let adminProducts = [];
let editingProductId = null;
let adminCashiers = [];
let editingCashierId = null;

async function adminApi(path, options = {}) {
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    if (adminToken) {
        headers['Authorization'] = 'Bearer ' + adminToken;
    } else {
        // If no token, try to get it from localStorage
        const token = localStorage.getItem('pos_token');
        if (token) {
            adminToken = token;
            headers['Authorization'] = 'Bearer ' + adminToken;
            console.log('Retrieved token from localStorage for API call');
        } else {
            console.warn('No admin token available for API call to:', path);
        }
    }
    
    console.log(`Making API call to: ${path}`);
    const res = await fetch(path, {
        ...options,
        headers,
    });
    
    if (!res.ok) {
        // If unauthorized (401), clear tokens and redirect to login immediately
        if (res.status === 401) {
            console.warn(`Unauthorized (401) for ${path} - clearing tokens and redirecting to login`);
            console.warn('This might indicate an expired or invalid token');
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            adminToken = null;
            adminUser = null;
            // Use window.location.replace to prevent back button issues
            window.location.replace('/');
            // Return a rejected promise to stop further execution
            return Promise.reject(new Error('Unauthorized - redirecting to login'));
        }
        const text = await res.text();
        console.error(`API call to ${path} failed with status ${res.status}:`, text);
        throw new Error(text || res.statusText);
    }
    if (res.status === 204) return null;
    return res.json();
}

async function loadAdminProducts() {
    const body = document.getElementById('products-body');
    if (!body) {
        // products-body only exists on /admin page, not on /store-settings page
        return;
    }
    console.log('=== loadAdminProducts STARTED ===');
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:16px;">Loading products...</td></tr>';
    
    try {
        adminProducts = await adminApi('/api/products');
        window.adminProducts = adminProducts;
        console.log(`Loaded ${adminProducts.length} products`);
        body.innerHTML = '';
        
        if (adminProducts.length === 0) {
            body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:16px;color:#fbbf24;">No products found</td></tr>';
            return;
        }
        
        adminProducts.forEach((p, index) => {
            const tr = document.createElement('tr');
            const expiryDate = p.expiry_date ? new Date(p.expiry_date).toLocaleDateString() : '-';
            
            // Create ALL cells and button manually
            const cells = [
                document.createElement('td'), // ID
                document.createElement('td'), // Name
                document.createElement('td'), // Barcode
                document.createElement('td'), // Stock
                document.createElement('td'), // Cost
                document.createElement('td'), // Price
                document.createElement('td'), // Expiry
                document.createElement('td')  // Edit button
            ];
            
            cells[0].textContent = p.id;
            cells[1].textContent = p.name;
            cells[2].textContent = p.barcode || '';
            cells[3].textContent = p.stock_qty;
            cells[4].textContent = parseFloat(p.cost_price).toFixed(2);
            cells[5].textContent = parseFloat(p.selling_price).toFixed(2);
            cells[6].textContent = expiryDate;
            
            // Create Edit button
            const editBtn = document.createElement('button');
            editBtn.className = 'small';
            editBtn.textContent = 'Edit';
            editBtn.setAttribute('data-product-id', p.id);
            
            // Add click handler
            editBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const pid = parseInt(this.getAttribute('data-product-id'), 10);
                if (typeof window.startEditProduct === 'function') {
                    window.startEditProduct(pid);
                }
                return false;
            });
            
            editBtn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                const pid = parseInt(this.getAttribute('data-product-id'), 10);
                if (typeof window.startEditProduct === 'function') {
                    window.startEditProduct(pid);
                }
                return false;
            };
            
            cells[7].appendChild(editBtn);
            
            // Add all cells to row
            cells.forEach(cell => tr.appendChild(cell));
            body.appendChild(tr);
        });
        
        console.log('=== Setting up event delegation ===');
        console.log('Total buttons created:', body.querySelectorAll('button').length);
        
        // Use event delegation on the table body with capture phase
        body.addEventListener('click', function(e) {
            console.log('Click detected on tbody, target:', e.target);
            console.log('Target tag:', e.target.tagName);
            console.log('Target class:', e.target.className);
            
            // Check if clicked element is a button
            if (e.target.tagName === 'BUTTON' && e.target.hasAttribute('data-product-id')) {
                const productId = parseInt(e.target.getAttribute('data-product-id'), 10);
                e.preventDefault();
                e.stopPropagation();
                
                try {
                    const formCard = document.getElementById('product-form-card');
                    if (formCard && typeof window.startEditProduct === 'function') {
                        window.startEditProduct(productId);
                    }
                } catch (error) {
                    console.error('ERROR:', error);
                }
                return false;
            }
        }, true); // Use capture phase
        
        // Also try on document level as ultimate fallback
        document.addEventListener('click', function(e) {
            if (e.target && e.target.classList && e.target.classList.contains('edit-product-btn')) {
                const productId = parseInt(e.target.getAttribute('data-product-id'), 10);
                e.preventDefault();
                e.stopPropagation();
                if (typeof window.startEditProduct === 'function') {
                    window.startEditProduct(productId);
                }
                return false;
            }
        }, true);
        
        if (typeof window.renderAdminProductsMobile === 'function') {
            window.renderAdminProductsMobile(adminProducts);
        }

        console.log('=== PRODUCTS LOADED ===');
        console.log('Total rows:', adminProducts.length);
        console.log('Edit buttons:', body.querySelectorAll('button').length);
        console.log('window.startEditProduct type:', typeof window.startEditProduct);
        
        // ABSOLUTE FALLBACK: Force add onclick to every button after they're created
        setTimeout(() => {
            const allEditButtons = body.querySelectorAll('button');
            console.log('=== SETTING UP BUTTON FALLBACK ===');
            console.log('Found', allEditButtons.length, 'edit buttons to setup');
            allEditButtons.forEach((btn, idx) => {
                const productId = btn.getAttribute('data-product-id');
                console.log(`Setting up button ${idx} for product ${productId}`);
                // Remove any existing onclick first
                btn.removeAttribute('onclick');
                // Add inline onclick as absolute fallback
                btn.onclick = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (typeof window.startEditProduct === 'function') {
                        window.startEditProduct(parseInt(productId, 10));
                    }
                    return false;
                };
                // Also set onclick attribute
                btn.setAttribute('onclick', `
                    if (typeof window.startEditProduct === 'function') {
                        window.startEditProduct(${productId});
                    }
                    return false;
                `);
                console.log(`Button ${idx} setup complete`);
            });
            console.log('=== ALL BUTTONS SETUP COMPLETE ===');
        }, 500);
    } catch (e) {
        console.error('Error loading products:', e);
        body.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:16px;color:#ef4444;">Error loading products: ${e.message}</td></tr>`;
    }
}

// Make startEditProduct globally accessible  
window.startEditProduct = function startEditProduct(id) {
    console.log('=== startEditProduct called with id:', id, '===');
    try {
    const p = adminProducts.find(x => x.id === id);
        if (!p) {
            console.error('Product not found with id:', id);
            return;
        }
        
        // Set editing state and populate form fields
    editingProductId = id;
    document.getElementById('prod-name').value = p.name;
    document.getElementById('prod-barcode').value = p.barcode || '';
    document.getElementById('prod-stock').value = Math.round(p.stock_qty) || 0;
    document.getElementById('prod-cost').value = p.cost_price;
    document.getElementById('prod-price').value = p.selling_price;
        
    // Set expiry date if it exists
    if (p.expiry_date) {
        const expiryDate = new Date(p.expiry_date);
        document.getElementById('prod-expiry').value = expiryDate.toISOString().split('T')[0];
    } else {
        document.getElementById('prod-expiry').value = '';
    }
    document.getElementById('prod-message').textContent = `Editing product #${id}`;
        
        // Show the product form panel - use the same approach as Add Product button
        const formCard = document.getElementById('product-form-card');
        console.log('Form card element:', formCard);
        if (!formCard) {
            console.error('ERROR: Product form card not found!');
            return;
        }
        
        // Check current state
        console.log('Current inline display:', formCard.style.display);
        console.log('Current computed display:', window.getComputedStyle(formCard).display);
        
        // Force show the form - same method as Add Product button
        formCard.style.removeProperty('display');
        formCard.style.display = 'block';
        formCard.style.setProperty('display', 'block', 'important');
        formCard.style.visibility = 'visible';
        formCard.style.setProperty('visibility', 'visible', 'important');
        formCard.style.opacity = '1';
        formCard.style.setProperty('opacity', '1', 'important');
        
        // Update button text to "Exit" immediately
        const btn = document.getElementById('btn-show-product-form');
        if (btn) {
            console.log('Updating button text to Exit (from edit)');
            btn.textContent = 'Exit';
            btn.innerHTML = 'Exit';
            console.log('Button text after update:', btn.textContent);
        } else {
            console.error('Button not found in startEditProduct!');
        }
        
        console.log('After setting - inline display:', formCard.style.display);
        console.log('After setting - computed display:', window.getComputedStyle(formCard).display);
        
        // Verify it's visible and scroll to it
        setTimeout(() => {
            const finalDisplay = window.getComputedStyle(formCard).display;
            console.log('Final computed display:', finalDisplay);
            if (finalDisplay === 'none') {
                console.error('ERROR: Form is still hidden after setting display!');
            } else {
                console.log('SUCCESS: Form should now be visible');
                formCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                // Focus on name field
                const nameField = document.getElementById('prod-name');
                if (nameField) {
                    nameField.focus();
                }
            }
        }, 300);
    } catch (error) {
        console.error('ERROR in startEditProduct:', error);
    }
}

// Function to show the product form panel
function showProductForm() {
    const formCard = document.getElementById('product-form-card');
    if (!formCard) {
        console.error('Product form card element not found!');
        return;
    }
    
    // Check if panel is already visible - if so, close it
    const isVisible = window.getComputedStyle(formCard).display !== 'none';
    if (isVisible) {
        clearProductForm();
        return;
    }
    
    console.log('Showing product form');
    
    // Update button text to "Exit" - the onclick handler should handle this, but ensure it's set
    const btn = document.getElementById('btn-show-product-form');
    if (btn) {
        btn.textContent = 'Exit';
        btn.innerHTML = 'Exit';
        btn.setAttribute('data-panel-open', 'true');
    }
    
    // Clear form and editing state
    editingProductId = null;
    document.getElementById('prod-name').value = '';
    document.getElementById('prod-barcode').value = '';
    document.getElementById('prod-stock').value = '0';
    document.getElementById('prod-cost').value = '';
    document.getElementById('prod-price').value = '';
    document.getElementById('prod-expiry').value = '';
    document.getElementById('prod-message').textContent = 'Add new product';
    
    // Force show the form
    formCard.style.removeProperty('display');
    formCard.style.removeProperty('visibility');
    formCard.style.setProperty('display', 'block', 'important');
    formCard.style.setProperty('visibility', 'visible', 'important');
    formCard.style.setProperty('opacity', '1', 'important');
    
    console.log('Form display set to:', formCard.style.display);
    console.log('Form computed display:', window.getComputedStyle(formCard).display);
    
    // Also update asynchronously to catch any edge cases
    setTimeout(() => {
        const btnAsync = document.getElementById('btn-show-product-form');
        if (btnAsync) {
            btnAsync.textContent = 'Exit';
            btnAsync.innerHTML = 'Exit';
            console.log('Button text after async update:', btnAsync.textContent);
        }
    }, 0);
    
    // Force update again after a short delay
    setTimeout(() => {
        const btnCheck = document.getElementById('btn-show-product-form');
        if (btnCheck && btnCheck.textContent !== 'Exit') {
            console.log('Button text was reset, fixing it again');
            btnCheck.textContent = 'Exit';
            btnCheck.innerHTML = 'Exit';
        }
    }, 50);
    
    // Scroll to form and focus
    setTimeout(() => {
        formCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        const nameInput = document.getElementById('prod-name');
        if (nameInput) {
            nameInput.focus();
        }
        // Update button text again after a short delay to ensure it's set
        const btnCheck = document.getElementById('btn-show-product-form');
        if (btnCheck) {
            console.log('Second update - setting button to Exit');
            btnCheck.textContent = 'Exit';
            btnCheck.innerHTML = 'Exit';
            // Force update by removing and re-adding text
            const currentText = btnCheck.textContent;
            btnCheck.textContent = '';
            btnCheck.textContent = 'Exit';
            console.log('Button text after second update:', btnCheck.textContent);
        }
    }, 100);
}

// Function to update Add Product button text based on panel visibility
function updateAddProductButtonText() {
    const btn = document.getElementById('btn-show-product-form');
    const formCard = document.getElementById('product-form-card');
    if (btn && formCard) {
        // Check both inline style and computed style
        const inlineDisplay = formCard.style.display;
        const computedDisplay = window.getComputedStyle(formCard).display;
        const isVisible = inlineDisplay === 'block' || (inlineDisplay !== 'none' && computedDisplay !== 'none');
        
        console.log('updateAddProductButtonText - isVisible:', isVisible, 'inlineDisplay:', inlineDisplay, 'computedDisplay:', computedDisplay);
        
        if (isVisible) {
            btn.textContent = 'Exit';
            btn.innerHTML = 'Exit';
            console.log('Button text set to Exit');
        } else {
            btn.textContent = '➕ Add Product';
            btn.innerHTML = '➕ Add Product';
            console.log('Button text set to Add Product');
        }
    } else {
        console.error('updateAddProductButtonText - Button or formCard not found!', btn, formCard);
    }
}

// Make functions globally accessible (after they're defined)
window.showProductForm = showProductForm;
window.updateAddProductButtonText = updateAddProductButtonText;

function clearProductForm() {
    editingProductId = null;
    document.getElementById('prod-name').value = '';
    document.getElementById('prod-barcode').value = '';
    document.getElementById('prod-stock').value = '0';
    document.getElementById('prod-cost').value = '';
    document.getElementById('prod-price').value = '';
    document.getElementById('prod-expiry').value = '';
    document.getElementById('prod-message').textContent = '';
    // Hide the product form panel after clearing
    const formCard = document.getElementById('product-form-card');
    if (formCard) {
        formCard.style.setProperty('display', 'none', 'important');
    }
    // Update button text back to "Add Product" immediately
    const btn = document.getElementById('btn-show-product-form');
    if (btn) {
        // Remove the data attribute to stop the observer from forcing "Exit"
        btn.removeAttribute('data-panel-open');
        // Disconnect observer if it exists
        if (btn._exitObserver) {
            btn._exitObserver.disconnect();
            btn._exitObserver = null;
        }
        btn.textContent = '➕ Add Product';
        btn.innerHTML = '➕ Add Product';
    }
}

async function saveProduct() {
    const msg = document.getElementById('prod-message');
    msg.textContent = '';
    const name = document.getElementById('prod-name').value.trim();
    const barcode = document.getElementById('prod-barcode').value.trim() || null;
    const stock = Math.max(0, Math.round(parseFloat(document.getElementById('prod-stock').value) || 0));
    const cost = parseFloat(document.getElementById('prod-cost').value) || 0;
    const price = parseFloat(document.getElementById('prod-price').value) || 0;

    if (!name) {
        msg.textContent = 'Name is required';
        return;
    }

    const expiryInput = document.getElementById('prod-expiry').value;
    const expiryDate = expiryInput ? expiryInput : null;
    
    const payload = {
        name,
        barcode,
        category_id: null,
        stock_qty: stock,
        cost_price: cost,
        selling_price: price,
        is_active: true,
        expiry_date: expiryDate,
    };

    try {
        if (editingProductId) {
            await adminApi(`/api/products/${editingProductId}`, {
                method: 'PUT',
                body: JSON.stringify(payload),
            });
            msg.textContent = 'Product updated';
        } else {
            await adminApi('/api/products', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            msg.textContent = 'Product created';
        }
        await loadAdminProducts();
        // Show success message briefly, then hide form
        setTimeout(() => {
        clearProductForm();
        }, 1500);
    } catch (e) {
        console.error(e);
        msg.textContent = 'Save failed';
    }
}

async function loadReport() {
    // Report elements only exist on /admin page, not on /store-settings page
    const fromInput = document.getElementById('rep-from');
    const toInput = document.getElementById('rep-to');
    const msg = document.getElementById('rep-message');
    
    if (!fromInput || !toInput || !msg) {
        // Report elements don't exist on this page - this is expected
        return;
    }
    
    msg.textContent = '';
    const fromDate = fromInput.value;
    const toDate = toInput.value;
    if (!fromDate || !toDate) {
        msg.textContent = 'Please select dates';
        return;
    }
    try {
        const rep = await adminApi(`/api/reports/summary?from_date=${fromDate}&to_date=${toDate}`);
        console.log('Report data received:', rep);
        console.log('total_stock_value:', rep.total_stock_value, typeof rep.total_stock_value);
        console.log('expected_profit:', rep.expected_profit, typeof rep.expected_profit);
        document.getElementById('rep-sales-count').textContent = rep.sales_count;
        document.getElementById('rep-gross').textContent = parseFloat(rep.gross_sales).toFixed(2);
        document.getElementById('rep-discounts').textContent = parseFloat(rep.discounts).toFixed(2);
        document.getElementById('rep-net').textContent = parseFloat(rep.net_sales).toFixed(2);
        document.getElementById('rep-profit').textContent = parseFloat(rep.profit).toFixed(2);
        
        const stockValue = rep.total_stock_value !== undefined && rep.total_stock_value !== null ? parseFloat(rep.total_stock_value) : 0;
        const expectedProfit = rep.expected_profit !== undefined && rep.expected_profit !== null ? parseFloat(rep.expected_profit) : 0;
        
        console.log('Calculated stockValue:', stockValue);
        console.log('Calculated expectedProfit:', expectedProfit);
        
        document.getElementById('rep-stock-value').textContent = stockValue.toFixed(2);
        document.getElementById('rep-expected-profit').textContent = expectedProfit.toFixed(2);
    } catch (e) {
        console.error('Error loading report:', e);
        msg.textContent = 'Report load failed';
    }
}

function initDates() {
    // Only set dates if elements exist (they're on /admin page, not on /store-settings page)
    const repFromEl = document.getElementById('rep-from');
    const repToEl = document.getElementById('rep-to');
    if (repFromEl && repToEl) {
        const today = new Date().toISOString().slice(0, 10);
        repFromEl.value = today;
        repToEl.value = today;
    }
}

function ensureAdmin() {
    const token = localStorage.getItem('pos_token');
    const userStr = localStorage.getItem('pos_user');
    
    console.log('=== ensureAdmin() called ===');
    console.log('Token exists:', !!token);
    console.log('User data exists:', !!userStr);
    
    if (!token || !userStr) {
        console.warn('No token or user data found - redirecting to login');
        window.location.href = '/';
        return false;
    }
    
    let user;
    try {
        user = JSON.parse(userStr);
        console.log('Parsed user data:', { username: user.username, role: user.role });
    } catch (e) {
        console.error('Failed to parse user data:', e);
        console.warn('Invalid user data - redirecting to login');
        window.location.href = '/';
        return false;
    }
    
    if (user.role !== 'admin') {
        console.warn(`User role is '${user.role}', not 'admin' - redirecting to login`);
        window.location.href = '/';
        return false;
    }
    
    adminToken = token;
    adminUser = user;
    
    const adminUserInfoEl = document.getElementById('admin-user-info');
    if (adminUserInfoEl) {
        adminUserInfoEl.textContent = `${adminUser.username} (${adminUser.role})`;
    }
    // Note: admin-user-info only exists on /admin page, not on other pages - this is expected
    
    console.log('Admin check passed successfully');
    return true;
}

async function loadStoreSettings() {
    try {
        const settings = await adminApi('/api/store-settings');
        
        // Only set values if elements exist (they're on /store-settings page, not /admin page)
        const storeNameEl = document.getElementById('store-name');
        if (storeNameEl) storeNameEl.value = settings.store_name || '';
        
        const storePhoneEl = document.getElementById('store-phone');
        if (storePhoneEl) storePhoneEl.value = settings.store_phone || '';
        
        const storeLocationEl = document.getElementById('store-location');
        if (storeLocationEl) storeLocationEl.value = settings.store_location || '';
        
        const notificationEmailEl = document.getElementById('notification-email');
        if (notificationEmailEl) notificationEmailEl.value = settings.notification_email || '';
        
        const lowStockEmailEnabledEl = document.getElementById('low-stock-email-enabled');
        if (lowStockEmailEnabledEl) lowStockEmailEnabledEl.checked = settings.low_stock_email_enabled || false;
        
        const defaultLowStockThresholdEl = document.getElementById('default-low-stock-threshold');
        if (defaultLowStockThresholdEl) defaultLowStockThresholdEl.value = settings.default_low_stock_threshold || 10;
    } catch (e) {
        console.error('Failed to load store settings:', e);
        const settingsMessageEl = document.getElementById('settings-message');
        if (settingsMessageEl) {
            settingsMessageEl.textContent = 'Failed to load settings';
        }
    }
}

async function saveStoreSettings() {
    const msg = document.getElementById('settings-message');
    msg.textContent = '';
    const storeName = document.getElementById('store-name').value.trim();
    const storePhone = document.getElementById('store-phone').value.trim() || null;
    const storeLocation = document.getElementById('store-location').value.trim() || null;

    if (!storeName) {
        msg.textContent = 'Store name is required';
        return;
    }

    const notificationEmail = document.getElementById('notification-email').value.trim() || null;
    const lowStockEmailEnabled = document.getElementById('low-stock-email-enabled').checked;
    const defaultLowStockThreshold = parseFloat(document.getElementById('default-low-stock-threshold').value) || 10.0;

    const payload = {
        store_name: storeName,
        store_phone: storePhone,
        store_location: storeLocation,
        notification_email: notificationEmail,
        low_stock_email_enabled: lowStockEmailEnabled,
        default_low_stock_threshold: defaultLowStockThreshold,
    };

    try {
        await adminApi('/api/store-settings', {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
        msg.textContent = 'Settings saved successfully';
    } catch (e) {
        console.error(e);
        msg.textContent = 'Save failed';
    }
}

async function checkNotifications() {
    const msg = document.getElementById('check-notifications-message');
    const btn = document.getElementById('btn-check-notifications');
    
    if (!msg || !btn) return;
    
    msg.style.display = 'block';
    msg.textContent = 'Checking products and creating notifications...';
    msg.style.color = 'rgba(255, 255, 255, 0.9)';
    msg.style.background = 'rgba(59, 130, 246, 0.2)';
    msg.style.border = '1px solid rgba(59, 130, 246, 0.5)';
    msg.style.borderRadius = '4px';
    btn.disabled = true;
    btn.textContent = 'Checking...';
    
    try {
        const response = await adminApi('/api/notifications/check-all', {
            method: 'POST'
        });
        
        msg.textContent = response.message || `Created ${response.notifications_created || 0} notification(s). Refresh the POS page to see them.`;
        msg.style.color = 'rgba(34, 197, 94, 1)';
        msg.style.background = 'rgba(34, 197, 94, 0.2)';
        msg.style.border = '1px solid rgba(34, 197, 94, 0.5)';
    } catch (e) {
        console.error('Check notifications error:', e);
        let errorMsg = 'Failed to check products';
        
        try {
            if (e.message) {
                const errorJson = JSON.parse(e.message);
                errorMsg = errorJson.detail || errorJson.message || e.message;
            } else {
                errorMsg = e.detail || e.message || 'Failed to check products';
            }
        } catch (parseError) {
            errorMsg = e.message || 'Failed to check products';
        }
        
        msg.textContent = `Error: ${errorMsg}`;
        msg.style.color = 'rgba(239, 68, 68, 1)';
        msg.style.background = 'rgba(239, 68, 68, 0.2)';
        msg.style.border = '1px solid rgba(239, 68, 68, 0.5)';
    } finally {
        btn.disabled = false;
        btn.textContent = '🔔 Check Products & Create Notifications';
    }
}

async function testEmail() {
    const msg = document.getElementById('test-email-message');
    const btn = document.getElementById('btn-test-email');
    
    if (!msg || !btn) return;
    
    msg.style.display = 'block';
    msg.textContent = 'Sending test email...';
    msg.style.color = 'rgba(255, 255, 255, 0.9)';
    msg.style.background = 'rgba(59, 130, 246, 0.2)';
    msg.style.border = '1px solid rgba(59, 130, 246, 0.5)';
    msg.style.borderRadius = '4px';
    btn.disabled = true;
    btn.textContent = 'Sending...';
    
    try {
        const response = await adminApi('/api/notifications/test-email', {
            method: 'POST'
        });
        
        msg.textContent = response.message || 'Test email sent successfully! Check your inbox.';
        msg.style.color = 'rgba(34, 197, 94, 1)';
        msg.style.background = 'rgba(34, 197, 94, 0.2)';
        msg.style.border = '1px solid rgba(34, 197, 94, 0.5)';
    } catch (e) {
        console.error('Test email error:', e);
        let errorMsg = 'Failed to send test email';
        
        // Try to parse JSON error response
        try {
            if (e.message) {
                const errorJson = JSON.parse(e.message);
                errorMsg = errorJson.detail || errorJson.message || e.message;
            } else {
                errorMsg = e.detail || e.message || 'Failed to send test email';
            }
        } catch (parseError) {
            // If not JSON, use the message as-is
            errorMsg = e.message || e.detail || 'Failed to send test email';
        }
        
        msg.textContent = `Error: ${errorMsg}`;
        msg.style.color = 'rgba(239, 68, 68, 1)';
        msg.style.background = 'rgba(239, 68, 68, 0.2)';
        msg.style.border = '1px solid rgba(239, 68, 68, 0.5)';
    } finally {
        btn.disabled = false;
        btn.textContent = '📧 Send Test Email';
    }
}

// Toggle More Settings section - make it globally accessible
window.toggleMoreSettings = function() {
    console.log('toggleMoreSettings called');
    
    // Try multiple ways to find the elements
    let content = document.getElementById('more-settings-content');
    let arrow = document.getElementById('more-settings-arrow');
    
    // If not found, try querySelector
    if (!content) {
        content = document.querySelector('#more-settings-content');
        console.log('Trying querySelector for content:', content);
    }
    if (!arrow) {
        arrow = document.querySelector('#more-settings-arrow');
        console.log('Trying querySelector for arrow:', arrow);
    }
    
    // If still not found, try finding within the settings panel
    if (!content) {
        const settingsPanel = document.getElementById('store-settings-panel');
        if (settingsPanel) {
            content = settingsPanel.querySelector('#more-settings-content');
            console.log('Trying within settings panel:', content);
        }
    }
    if (!arrow) {
        const settingsPanel = document.getElementById('store-settings-panel');
        if (settingsPanel) {
            arrow = settingsPanel.querySelector('#more-settings-arrow');
            console.log('Trying arrow within settings panel:', arrow);
        }
    }
    
    console.log('Content element:', content);
    console.log('Arrow element:', arrow);
    
    if (!content) {
        console.error('more-settings-content not found after all attempts');
        console.log('All elements with id more-settings-content:', document.querySelectorAll('[id="more-settings-content"]'));
        alert('More settings content not found. Please refresh the page.');
        return;
    }
    if (!arrow) {
        console.error('more-settings-arrow not found after all attempts');
        return;
    }
    
    // Check computed style to handle both inline and CSS styles
    const computedStyle = window.getComputedStyle(content);
    const currentDisplay = computedStyle.display;
    const inlineDisplay = content.style.display;
    const isHidden = currentDisplay === 'none' || inlineDisplay === 'none' || inlineDisplay === '';
    
    console.log('Current computed display:', currentDisplay);
    console.log('Current inline display:', inlineDisplay);
    console.log('isHidden:', isHidden);
    
    if (isHidden) {
        // Add class and set display
        content.classList.add('more-settings-visible');
        content.style.setProperty('display', 'block', 'important');
        content.style.setProperty('visibility', 'visible', 'important');
        content.style.setProperty('opacity', '1', 'important');
        content.style.removeProperty('margin-top'); // Remove margin-top from inline style if it exists
        content.style.setProperty('margin-top', '16px', 'important');
        arrow.textContent = '▲';
        console.log('Expanded more settings - display set to block');
        
        // Force a reflow to ensure the change takes effect
        void content.offsetHeight;
        
        // Verify it's visible
        const afterStyle = window.getComputedStyle(content);
        console.log('After setting - computed display:', afterStyle.display);
        console.log('After setting - computed visibility:', afterStyle.visibility);
    } else {
        content.classList.remove('more-settings-visible');
        content.style.setProperty('display', 'none', 'important');
        arrow.textContent = '▼';
        console.log('Collapsed more settings');
    }
};

// Add event listener for test email button when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        const btnMoreSettings = document.getElementById('btn-more-settings');
        if (btnMoreSettings) {
            btnMoreSettings.addEventListener('click', toggleMoreSettings);
        }
        
        const btnTestEmail = document.getElementById('btn-test-email');
        if (btnTestEmail) {
            btnTestEmail.addEventListener('click', testEmail);
        }
        
        const btnCheckNotifications = document.getElementById('btn-check-notifications');
        if (btnCheckNotifications) {
            btnCheckNotifications.addEventListener('click', checkNotifications);
        }
    });
} else {
    // DOM already loaded
    const btnMoreSettings = document.getElementById('btn-more-settings');
    if (btnMoreSettings) {
        btnMoreSettings.addEventListener('click', toggleMoreSettings);
    }
    
    const btnTestEmail = document.getElementById('btn-test-email');
    if (btnTestEmail) {
        btnTestEmail.addEventListener('click', testEmail);
    }
    
    const btnCheckNotifications = document.getElementById('btn-check-notifications');
    if (btnCheckNotifications) {
        btnCheckNotifications.addEventListener('click', checkNotifications);
    }
}

async function loadCashiers() {
    try {
        adminCashiers = await adminApi('/api/users');
        renderCashiers();
    } catch (e) {
        console.error('Failed to load cashiers:', e);
        document.getElementById('cashiers-body').innerHTML = 
            '<tr><td colspan="5" style="text-align:center;padding:16px;color:rgba(255,255,255,0.5);">Failed to load cashiers</td></tr>';
    }
}

function renderCashiers() {
    const body = document.getElementById('cashiers-body');
    if (!body) return;
    
    if (adminCashiers.length === 0) {
        body.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:16px;color:rgba(255,255,255,0.5);">No cashiers found</td></tr>';
        return;
    }
    
    body.innerHTML = adminCashiers.map(c => `
        <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
            <td style="padding:8px;">${escapeHtml(c.username)}</td>
            <td style="padding:8px;">${escapeHtml(c.full_name || '-')}</td>
            <td style="padding:8px;">
                <span style="padding:2px 8px;border-radius:4px;background:${c.role === 'admin' ? 'rgba(239,68,68,0.3)' : 'rgba(79,70,229,0.3)'};">
                    ${escapeHtml(c.role)}
                </span>
            </td>
            <td style="padding:8px;">
                <span style="padding:2px 8px;border-radius:4px;background:${c.is_active ? 'rgba(34,197,94,0.3)' : 'rgba(107,114,128,0.3)'};">
                    ${c.is_active ? 'Active' : 'Inactive'}
                </span>
            </td>
            <td style="padding:8px;">
                <button onclick="startEditCashier(${c.id})" class="small" style="margin-right:4px;">Edit</button>
                ${c.id !== adminUser?.id ? `
                    <button onclick="toggleCashierStatus(${c.id}, ${!c.is_active})" class="small" style="margin-right:4px;">
                        ${c.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button onclick="deleteCashier(${c.id})" class="small danger">Delete</button>
                ` : '<span style="color:rgba(255,255,255,0.5);font-size:12px;">Current User</span>'}
            </td>
        </tr>
    `).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function startEditCashier(id) {
    const c = adminCashiers.find(x => x.id === id);
    if (!c) return;
    editingCashierId = id;
    document.getElementById('cashier-username').value = c.username;
    document.getElementById('cashier-fullname').value = c.full_name || '';
    document.getElementById('cashier-password').value = '';
    document.getElementById('cashier-role').value = c.role;
    document.getElementById('cashier-message').textContent = `Editing cashier: ${c.username}`;
}

function clearCashierForm() {
    editingCashierId = null;
    document.getElementById('cashier-username').value = '';
    document.getElementById('cashier-fullname').value = '';
    document.getElementById('cashier-password').value = '';
    document.getElementById('cashier-role').value = 'cashier';
    document.getElementById('cashier-message').textContent = '';
}

async function saveCashier() {
    const msg = document.getElementById('cashier-message');
    msg.textContent = '';
    const username = document.getElementById('cashier-username').value.trim();
    const fullname = document.getElementById('cashier-fullname').value.trim() || null;
    const password = document.getElementById('cashier-password').value;
    const role = document.getElementById('cashier-role').value;
    
    if (!username) {
        msg.textContent = 'Username is required';
        return;
    }
    
    if (!editingCashierId && !password) {
        msg.textContent = 'Password is required for new cashiers';
        return;
    }
    
    try {
        if (editingCashierId) {
            // Update existing
            const updateData = {
                username: username,
                full_name: fullname,
                role: role,
            };
            if (password) {
                updateData.password = password;
            }
            await adminApi(`/api/users/${editingCashierId}`, {
                method: 'PUT',
                body: JSON.stringify(updateData),
            });
            msg.textContent = 'User updated successfully';
        } else {
            // Create new
            await adminApi('/api/users', {
                method: 'POST',
                body: JSON.stringify({
                    username: username,
                    full_name: fullname,
                    password: password,
                    role: role,
                }),
            });
            msg.textContent = 'User added successfully';
        }
        clearCashierForm();
        await loadCashiers();
    } catch (e) {
        console.error(e);
        msg.textContent = e.message || 'Operation failed';
    }
}

async function toggleCashierStatus(id, activate) {
    const c = adminCashiers.find(x => x.id === id);
    if (!c) return;
    
    if (!confirm(`Are you sure you want to ${activate ? 'activate' : 'deactivate'} ${c.username}?`)) {
        return;
    }
    
    try {
        await adminApi(`/api/users/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ is_active: activate }),
        });
        await loadCashiers();
    } catch (e) {
        console.error(e);
        alert(e.message || 'Operation failed');
    }
}

async function deleteCashier(id) {
    const c = adminCashiers.find(x => x.id === id);
    if (!c) return;
    
    // Prevent deleting your own account - show clear warning
    if (adminUser && c.id === adminUser.id) {
        alert(`⚠️ WARNING: You cannot delete your own account!\n\nYou are currently logged in as "${c.username}" (${c.role}).\n\nTo delete this account:\n1. Create another admin account first\n2. Log out and log in with the new admin account\n3. Then you can delete this account`);
        return;
    }
    
    if (!confirm(`Are you sure you want to delete ${c.username}? This action cannot be undone.`)) {
        return;
    }
    
    try {
        await adminApi(`/api/users/${id}`, {
            method: 'DELETE',
        });
        await loadCashiers();
    } catch (e) {
        console.error(e);
        const errorMsg = e.message || 'Delete failed';
        // Check if the error is about deleting own account and show enhanced warning
        if (errorMsg.includes('your own account') || errorMsg.includes('Cannot delete your own')) {
            alert(`⚠️ ${errorMsg}\n\nYou cannot delete your own account while logged in. Please create another admin account and log in with it first.`);
        } else {
            alert(errorMsg);
        }
    }
}

// Define factoryReset function on window immediately
window.factoryReset = async function factoryReset() {
    console.log('factoryReset function called');
    const msg = document.getElementById('reset-message');
    if (!msg) {
        console.error('reset-message element not found');
        alert('Error: Reset message element not found. Please refresh the page.');
        return;
    }
    msg.textContent = '';
    
    // First confirmation: Type text to confirm
    const confirmText = 'FACTORY RESET';
    const userConfirm = prompt(
        `⚠️ WARNING: This will PERMANENTLY DELETE ALL DATA!\n\n` +
        `This includes:\n` +
        `- All products\n` +
        `- All sales records\n` +
        `- All customers\n` +
        `- All layby transactions\n` +
        `- All users\n` +
        `- All settings\n\n` +
        `Type "${confirmText}" (exactly as shown) to continue:`
    );
    
    if (userConfirm !== confirmText) {
        msg.textContent = 'Factory reset cancelled.';
        msg.style.color = 'rgba(255, 255, 255, 0.7)';
        return;
    }
    
    // Second confirmation: Admin password required
    const adminPassword = prompt(
        `🔒 ADMIN PASSWORD REQUIRED\n\n` +
        `Enter your admin password to confirm factory reset:\n` +
        `(This action cannot be undone)`
    );
    
    if (!adminPassword || adminPassword.trim() === '') {
        msg.textContent = 'Factory reset cancelled. Admin password is required.';
        msg.style.color = 'rgba(220, 38, 38, 1)';
        return;
    }
    
    try {
        msg.textContent = 'Resetting to factory settings... Please wait...';
        msg.style.color = 'rgba(255, 255, 255, 0.9)';
        
        const response = await adminApi('/api/factory-reset', {
            method: 'POST',
            body: JSON.stringify({
                admin_password: adminPassword
            }),
        });
        
        msg.textContent = response.message || 'Factory reset completed successfully. Redirecting to login...';
        msg.style.color = 'rgba(34, 197, 94, 1)';
        
        // Clear local storage immediately
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        adminToken = null;
        adminUser = null;
        
        // Redirect to login page immediately
        setTimeout(() => {
            window.location.href = '/';
        }, 1000);
    } catch (e) {
        console.error(e);
        const errorMsg = e.message || 'Factory reset failed';
        msg.textContent = `Error: ${errorMsg}`;
        msg.style.color = 'rgba(220, 38, 38, 1)';
    }
}

// Make functions globally accessible
window.startEditCashier = startEditCashier;
window.toggleCashierStatus = toggleCashierStatus;
window.deleteCashier = deleteCashier;
// factoryReset is already defined on window above

// Switch between settings pages
window.switchSettingsPage = function(pageNum) {
    console.log('Switching to settings page:', pageNum);
    
    // Hide all pages
    const page1 = document.getElementById('settings-page-1');
    const page2 = document.getElementById('settings-page-2');
    
    // Remove active class from all buttons
    const buttons = document.querySelectorAll('.settings-page-btn');
    buttons.forEach(btn => btn.classList.remove('active'));
    
    // Show selected page and activate its button
    if (pageNum === 1) {
        if (page1) {
            page1.style.display = 'flex';
            page1.style.setProperty('display', 'flex', 'important');
        }
        if (page2) {
            page2.style.display = 'none';
            page2.style.setProperty('display', 'none', 'important');
        }
        const btn1 = document.querySelector('.settings-page-btn[data-page="1"]');
        if (btn1) btn1.classList.add('active');
    } else if (pageNum === 2) {
        if (page1) {
            page1.style.display = 'none';
            page1.style.setProperty('display', 'none', 'important');
        }
        if (page2) {
            page2.style.display = 'flex';
            page2.style.setProperty('display', 'flex', 'important');
        }
        const btn2 = document.querySelector('.settings-page-btn[data-page="2"]');
        if (btn2) btn2.classList.add('active');
    }
    
    // Scroll to top of settings content
    const settingsContent = document.querySelector('.store-settings-content');
    if (settingsContent) {
        settingsContent.scrollTop = 0;
    }
};

// Make functions globally accessible
window.toggleSettingsPanel = function() {
    console.log('toggleSettingsPanel called');
    const panel = document.getElementById('store-settings-panel');
    const reportPanel = document.getElementById('summary-report-panel');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (!panel) {
        console.error('store-settings-panel not found');
        return;
    }
    if (!backdrop) {
        console.error('panel-backdrop not found');
        return;
    }
    
    // Ensure More Settings button has event listener when panel opens
    setTimeout(() => {
        const btnMoreSettings = document.getElementById('btn-more-settings');
        const content = document.getElementById('more-settings-content');
        const arrow = document.getElementById('more-settings-arrow');
        
        console.log('Setting up More Settings button - Button:', !!btnMoreSettings, 'Content:', !!content, 'Arrow:', !!arrow);
        
        if (btnMoreSettings && !btnMoreSettings.dataset.listenerAttached) {
            btnMoreSettings.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('More Settings button clicked via event listener');
                
                // Find elements fresh each time
                let contentEl = document.getElementById('more-settings-content');
                let arrowEl = document.getElementById('more-settings-arrow');
                
                if (!contentEl) {
                    const panel = document.getElementById('store-settings-panel');
                    if (panel) {
                        contentEl = panel.querySelector('#more-settings-content');
                    }
                }
                if (!arrowEl) {
                    const panel = document.getElementById('store-settings-panel');
                    if (panel) {
                        arrowEl = panel.querySelector('#more-settings-arrow');
                    }
                }
                
                if (contentEl && arrowEl) {
                    const isHidden = contentEl.style.display === 'none' || window.getComputedStyle(contentEl).display === 'none';
                    if (isHidden) {
                        contentEl.style.setProperty('display', 'block', 'important');
                        contentEl.style.setProperty('visibility', 'visible', 'important');
                        contentEl.style.setProperty('opacity', '1', 'important');
                        contentEl.classList.add('more-settings-visible');
                        arrowEl.textContent = '▲';
                        console.log('Expanded via event listener');
                    } else {
                        contentEl.style.setProperty('display', 'none', 'important');
                        contentEl.classList.remove('more-settings-visible');
                        arrowEl.textContent = '▼';
                        console.log('Collapsed via event listener');
                    }
                } else {
                    console.error('Could not find content or arrow elements');
                    if (typeof window.toggleMoreSettings === 'function') {
                        window.toggleMoreSettings();
                    }
                }
                return false;
            });
            btnMoreSettings.dataset.listenerAttached = 'true';
            console.log('More Settings button listener attached');
        }
    }, 200);
    
    // Check if panel is currently visible
    const computedStyle = window.getComputedStyle(panel);
    const isVisible = computedStyle.display !== 'none' && computedStyle.display !== '';
    console.log('Toggle settings panel, isVisible:', isVisible, 'computed display:', computedStyle.display);
    
    // Close report panel if open
    if (reportPanel) {
        reportPanel.style.setProperty('display', 'none', 'important');
    }
    
    // Toggle settings panel
    if (isVisible) {
        // Hide panel
        panel.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
        console.log('Settings panel hidden');
    } else {
        // Show panel
        panel.style.setProperty('display', 'block', 'important');
        panel.style.setProperty('visibility', 'visible', 'important');
        panel.style.setProperty('opacity', '1', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        console.log('Settings panel shown');
        
        // Reset to page 1 when panel opens
        setTimeout(() => {
            if (typeof window.switchSettingsPage === 'function') {
                window.switchSettingsPage(1);
            }
        }, 100);
        
        // Ensure More Settings button has event listener when panel opens
        setTimeout(() => {
            const btnMoreSettings = document.getElementById('btn-more-settings');
            if (btnMoreSettings) {
                // Remove any existing listeners first
                const newBtn = btnMoreSettings.cloneNode(true);
                btnMoreSettings.parentNode.replaceChild(newBtn, btnMoreSettings);
                
                // Add event listener to new button
                newBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('More Settings button clicked');
                    if (typeof window.toggleMoreSettings === 'function') {
                        window.toggleMoreSettings();
                    }
                    return false;
                });
                console.log('More Settings button listener attached after panel open');
            }
        }, 100);
    }
}

let allWithdrawals = [];

window.loadWithdrawals = async function() {
    console.log('=== loadWithdrawals called ===');
    const body = document.getElementById('withdrawals-body');
    const msg = document.getElementById('withdrawals-message');
    
    console.log('Withdrawals body found:', !!body);
    console.log('Withdrawals message found:', !!msg);
    
    if (!body) {
        console.error('Withdrawals body element not found');
        return;
    }
    
    body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;">Loading withdrawals...</td></tr>';
    if (msg) msg.textContent = '';
    
    try {
        console.log('Calling adminApi for withdrawals...');
        allWithdrawals = await adminApi('/api/withdrawals?limit=1000');
        console.log(`Loaded ${allWithdrawals.length} withdrawals:`, allWithdrawals);
        filterAndRenderWithdrawals();
    } catch (e) {
        console.error('Error loading withdrawals:', e);
        const errorMsg = e.message || 'Unknown error';
        body.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:16px;color:rgba(239, 68, 68, 1);">Error loading withdrawals: ${errorMsg}</td></tr>`;
        if (msg) {
            msg.textContent = `Failed to load withdrawals: ${errorMsg}`;
            msg.style.color = 'rgba(239, 68, 68, 1)';
        }
    }
};

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
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;color:rgba(255,255,255,0.5);">No withdrawals found</td></tr>';
        updateWithdrawalTotals([]);
        return;
    }
    
    filtered.forEach(w => {
        const tr = document.createElement('tr');
        const date = new Date(w.created_at);
        const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        
        tr.innerHTML = `
            <td>${dateStr}</td>
            <td>${w.receipt_number || 'N/A'}</td>
            <td style="font-weight:bold;color:rgba(239, 68, 68, 1);">$${parseFloat(w.amount).toFixed(2)}</td>
            <td>${w.reason}</td>
            <td>${w.cashier_name || 'Unknown'}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${w.notes || ''}">${w.notes || '-'}</td>
        `;
        body.appendChild(tr);
    });
    
    updateWithdrawalTotals(filtered);
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
    if (msg) {
        msg.textContent = 'Syncing withdrawals to Google Sheets...';
        msg.style.color = 'rgba(255, 255, 255, 0.9)';
    }
    
    try {
        const result = await adminApi('/api/backup/sync-withdrawals', {
            method: 'POST'
        });
        
        if (msg) {
            if (result.success) {
                msg.textContent = result.message || 'Withdrawals synced successfully';
                msg.style.color = 'rgba(34, 197, 94, 1)';
            } else {
                msg.textContent = result.message || 'Sync failed';
                msg.style.color = 'rgba(239, 68, 68, 1)';
            }
        }
    } catch (e) {
        console.error('Error syncing withdrawals:', e);
        if (msg) {
            msg.textContent = 'Sync failed: ' + (e.message || 'Unknown error');
            msg.style.color = 'rgba(239, 68, 68, 1)';
        }
    }
}

window.toggleWithdrawalsPanel = function() {
    console.log('=== toggleWithdrawalsPanel called ===');
    const panel = document.getElementById('withdrawals-history-panel');
    const settingsPanel = document.getElementById('store-settings-panel');
    const reportPanel = document.getElementById('summary-report-panel');
    const backdrop = document.getElementById('panel-backdrop');
    
    console.log('Panel found:', !!panel);
    console.log('Backdrop found:', !!backdrop);
    
    if (!panel) {
        console.error('withdrawals-history-panel not found');
        alert('Withdrawals panel element not found. Please refresh the page.');
        return;
    }
    if (!backdrop) {
        console.error('panel-backdrop not found');
        alert('Backdrop element not found. Please refresh the page.');
        return;
    }
    
    // Check if panel is currently visible
    const computedStyle = window.getComputedStyle(panel);
    const isVisible = computedStyle.display !== 'none' && computedStyle.display !== '';
    console.log('Panel current display:', computedStyle.display);
    console.log('Panel isVisible:', isVisible);
    
    // Close other panels if open
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    if (reportPanel) {
        reportPanel.style.setProperty('display', 'none', 'important');
    }
    
    // Toggle withdrawals panel
    if (isVisible) {
        // Hide panel
        panel.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
        console.log('Withdrawals panel hidden');
    } else {
        // Show panel
        console.log('Showing withdrawals panel...');
        panel.style.setProperty('display', 'block', 'important');
        panel.style.setProperty('visibility', 'visible', 'important');
        panel.style.setProperty('opacity', '1', 'important');
        panel.style.setProperty('z-index', '9999', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        backdrop.style.setProperty('z-index', '9998', 'important');
        
        // Verify it's visible
        const newStyle = window.getComputedStyle(panel);
        console.log('Panel display after show:', newStyle.display);
        console.log('Panel visibility after show:', newStyle.visibility);
        console.log('Panel opacity after show:', newStyle.opacity);
        console.log('Panel z-index after show:', newStyle.zIndex);
        
        // Load withdrawals when panel is opened
        console.log('Loading withdrawals...');
        loadWithdrawals();
    }
}

window.toggleReportPanel = function() {
    console.log('toggleReportPanel called');
    const panel = document.getElementById('summary-report-panel');
    const settingsPanel = document.getElementById('store-settings-panel');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (!panel) {
        console.error('summary-report-panel not found');
        return;
    }
    if (!backdrop) {
        console.error('panel-backdrop not found');
        return;
    }
    
    // Check if panel is currently visible
    const computedStyle = window.getComputedStyle(panel);
    const isVisible = computedStyle.display !== 'none' && computedStyle.display !== '';
    console.log('Toggle report panel, isVisible:', isVisible, 'computed display:', computedStyle.display);
    
    // Close settings panel if open
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    
    // Toggle report panel
    if (isVisible) {
        // Hide panel
        panel.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
        console.log('Report panel hidden');
    } else {
        // Show panel
        panel.style.setProperty('display', 'block', 'important');
        panel.style.setProperty('visibility', 'visible', 'important');
        panel.style.setProperty('opacity', '1', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        console.log('Report panel shown');
    }
}

window.toggleShiftsPanel = function() {
    console.log('toggleShiftsPanel called');
    const panel = document.getElementById('shifts-panel');
    const backdrop = document.getElementById('panel-backdrop');
    const settingsPanel = document.getElementById('store-settings-panel');
    const reportPanel = document.getElementById('summary-report-panel');
    
    if (!panel) {
        console.error('shifts-panel not found');
        return;
    }
    if (!backdrop) {
        console.error('panel-backdrop not found');
        return;
    }
    
    const isVisible = window.getComputedStyle(panel).display !== 'none';
    
    // Close other panels
    if (settingsPanel) settingsPanel.style.setProperty('display', 'none', 'important');
    if (reportPanel) reportPanel.style.setProperty('display', 'none', 'important');
    
    if (isVisible) {
        panel.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
        console.log('Shifts panel hidden');
    } else {
        // Check if user is cashier - if so, require admin/supervisor password
        if (adminUser && adminUser.role === 'cashier') {
            // Show password prompt modal
            showShiftPasswordModal();
        } else {
            // Admin or supervisor can access directly
            openShiftPanel();
        }
    }
};

function showShiftPasswordModal() {
    const modal = document.getElementById('shift-password-modal');
    const backdrop = document.getElementById('panel-backdrop');
    const passwordInput = document.getElementById('shift-admin-password');
    const errorDiv = document.getElementById('shift-password-error');
    
    if (!modal || !passwordInput || !errorDiv) {
        console.error('Shift password modal elements not found');
        return;
    }
    
    // Reset form
    passwordInput.value = '';
    errorDiv.style.display = 'none';
    errorDiv.textContent = '';
    
    // Show modal
    modal.style.setProperty('display', 'block', 'important');
    modal.style.setProperty('visibility', 'visible', 'important');
    modal.style.setProperty('opacity', '1', 'important');
    if (backdrop) {
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
    }
    
    // Focus password input
    setTimeout(() => passwordInput.focus(), 100);
}

function hideShiftPasswordModal() {
    const modal = document.getElementById('shift-password-modal');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (modal) {
        modal.style.setProperty('display', 'none', 'important');
    }
    // Don't hide backdrop here - it will be managed by openShiftPanel
}

async function verifyShiftPassword() {
    const passwordInput = document.getElementById('shift-admin-password');
    const errorDiv = document.getElementById('shift-password-error');
    const verifyBtn = document.getElementById('btn-verify-shift-password');
    
    if (!passwordInput || !errorDiv || !verifyBtn) {
        console.error('Password verification elements not found');
        return;
    }
    
    const password = passwordInput.value.trim();
    
    if (!password) {
        errorDiv.style.display = 'block';
        errorDiv.textContent = 'Please enter admin/supervisor password';
        return;
    }
    
    // Disable button and show loading
    verifyBtn.disabled = true;
    verifyBtn.textContent = 'Verifying...';
    errorDiv.style.display = 'none';
    
    try {
        const response = await adminApi('/api/shifts/verify-admin-password', {
            method: 'POST',
            body: JSON.stringify({ password: password })
        });
        
        if (response && response.ok) {
            // Password verified - hide modal and open shift panel
            hideShiftPasswordModal();
            openShiftPanel();
        } else {
            throw new Error('Password verification failed');
        }
    } catch (error) {
        console.error('Password verification error:', error);
        errorDiv.style.display = 'block';
        errorDiv.textContent = error.message || 'Invalid admin/supervisor password';
        passwordInput.value = '';
        passwordInput.focus();
    } finally {
        verifyBtn.disabled = false;
        verifyBtn.textContent = 'Verify & Open Shift Panel';
    }
}

function openShiftPanel() {
    const panel = document.getElementById('shifts-panel');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (!panel) {
        console.error('shifts-panel not found');
        return;
    }
    
    panel.style.setProperty('display', 'block', 'important');
    panel.style.setProperty('visibility', 'visible', 'important');
    panel.style.setProperty('opacity', '1', 'important');
    if (backdrop) {
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
    }
    console.log('Shifts panel shown');
    
    // Load data
    if (typeof loadActiveShift === 'function') {
        loadActiveShift();
    }
    if (typeof loadShiftsHistory === 'function') {
        loadShiftsHistory();
    }
}

window.closeAllPanels = function() {
    const settingsPanel = document.getElementById('store-settings-panel');
    const reportPanel = document.getElementById('summary-report-panel');
    const withdrawalsPanel = document.getElementById('withdrawals-history-panel');
    const importModal = document.getElementById('import-inventory-modal');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    if (reportPanel) {
        reportPanel.style.setProperty('display', 'none', 'important');
    }
    if (withdrawalsPanel) {
        withdrawalsPanel.style.setProperty('display', 'none', 'important');
    }
    if (importModal) {
        importModal.style.setProperty('display', 'none', 'important');
    }
    if (backdrop) {
        backdrop.style.setProperty('display', 'none', 'important');
    }
    console.log('All panels closed');
}

function triggerFileInput() {
    const fileInput = document.getElementById('inventory-file-input');
    if (fileInput) {
        console.log('Triggering file input click directly');
        fileInput.click();
    } else {
        console.error('File input not found');
    }
}

function setupFileInputHandlers() {
    console.log('=== setupFileInputHandlers called ===');
    const fileInput = document.getElementById('inventory-file-input');
    const fileLabel = document.getElementById('inventory-file-label');
    const btnChooseFile = document.getElementById('btn-choose-file');
    
    console.log('File input found:', !!fileInput, 'File label found:', !!fileLabel, 'Choose file button found:', !!btnChooseFile);
    
    if (!fileInput) {
        // File input only exists on /admin page, not on /store-settings page
        return;
    }
    
    // Set up change handler
    fileInput.addEventListener('change', function(e) {
        console.log('File input change event fired');
        const fileName = document.getElementById('selected-file-name');
        const uploadBtn = document.getElementById('btn-upload-inventory');
        if (e.target.files && e.target.files.length > 0) {
            clearAndroidPendingImport();
            if (fileName) fileName.textContent = 'Selected: ' + e.target.files[0].name;
            if (uploadBtn) uploadBtn.disabled = false;
            console.log('File selected:', e.target.files[0].name);
        } else if (!hasAndroidPendingImport()) {
            if (fileName) fileName.textContent = '';
            if (uploadBtn) uploadBtn.disabled = true;
        }
    });
    console.log('File input change handler attached');
    
    // Set up label click handler
    if (fileLabel) {
        fileLabel.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('=== File label clicked ===');
            triggerFileInput();
            return false;
        });
        
        fileLabel.style.cursor = 'pointer';
        fileLabel.style.userSelect = 'none';
        
        // Add hover effect
        fileLabel.addEventListener('mouseenter', function() {
            this.style.background = 'rgba(255,255,255,0.1)';
        });
        fileLabel.addEventListener('mouseleave', function() {
            this.style.background = 'rgba(255,255,255,0.05)';
        });
        
        console.log('File label handlers set up successfully');
    } else {
        console.error('File label not found');
    }
    
    // Set up choose file button
    if (btnChooseFile) {
        btnChooseFile.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('=== Choose file button clicked ===');
            triggerFileInput();
            return false;
        });
        console.log('Choose file button handler attached');
    }
}

function showImportModal() {
    console.log('showImportModal called');
    const modal = document.getElementById('import-inventory-modal');
    const backdrop = document.getElementById('panel-backdrop');
    console.log('Modal element:', modal, 'Backdrop element:', backdrop);
    if (modal && backdrop) {
        modal.style.setProperty('display', 'block', 'important');
        modal.style.setProperty('visibility', 'visible', 'important');
        modal.style.setProperty('opacity', '1', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        console.log('Import modal should be visible now');
        
        // Set up file input handlers after modal is shown
        setTimeout(() => {
            setupFileInputHandlers();
        }, 100);
    } else {
        console.error('Modal or backdrop not found:', { modal: !!modal, backdrop: !!backdrop });
    }
}

// Make functions globally accessible
window.showImportModal = showImportModal;
window.hideImportModal = hideImportModal;
window.setupFileInputHandlers = setupFileInputHandlers;
window.triggerFileInput = triggerFileInput;
window.uploadInventoryFile = uploadInventoryFile;
window.uploadInventoryCsvFile = uploadInventoryCsvFile;

function hideImportModal() {
    const modal = document.getElementById('import-inventory-modal');
    const backdrop = document.getElementById('panel-backdrop');
    if (modal && backdrop) {
        modal.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
    }
    // Reset file input
    const fileInput = document.getElementById('inventory-file-input');
    const fileName = document.getElementById('selected-file-name');
    const uploadBtn = document.getElementById('btn-upload-inventory');
    if (fileInput) fileInput.value = '';
    if (fileName) fileName.textContent = '';
    if (uploadBtn) uploadBtn.disabled = true;
    clearAndroidPendingImport();
}

function parseApiErrorText(text) {
    if (!text) return 'Request failed';
    try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') return j.detail;
        if (Array.isArray(j.detail) && j.detail.length > 0) {
            return j.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
        }
    } catch (_) {}
    return text.length > 400 ? text.slice(0, 400) + '…' : text;
}

function getImportAuthToken() {
    if (adminToken) return adminToken;
    const t = localStorage.getItem('pos_token');
    if (t) adminToken = t;
    return t;
}

function hasAndroidPendingImport() {
    try {
        return (
            typeof PosAndroidImport !== 'undefined' &&
            PosAndroidImport.hasPendingImport &&
            PosAndroidImport.hasPendingImport()
        );
    } catch (e) {
        return false;
    }
}

function clearAndroidPendingImport() {
    try {
        if (typeof PosAndroidImport !== 'undefined' && PosAndroidImport.clearPendingImport) {
            PosAndroidImport.clearPendingImport();
        }
    } catch (e) {
        /* ignore */
    }
}

/** Called from Android after the user picks a file in the system chooser. */
window.onPosAndroidImportFileReady = function (fileName) {
    const fileNameEl = document.getElementById('selected-file-name');
    const uploadBtn = document.getElementById('btn-upload-inventory');
    if (fileNameEl) {
        fileNameEl.textContent = 'Selected: ' + (fileName || 'file');
    }
    if (uploadBtn) uploadBtn.disabled = false;
};

function formatImportResultMessage(result) {
    let message = 'Import completed!\n';
    message += `Total rows: ${result.total_rows || 0}\n`;
    message += `Created: ${result.created || 0}\n`;
    message += `Updated: ${result.updated || 0}\n`;
    if (result.merged_rows) {
        message += `Duplicate rows merged in file: ${result.merged_rows}\n`;
    }
    message += `Skipped: ${result.skipped || 0}`;
    if (result.file_merged_rows) {
        message += `\nDuplicate lines merged in file: ${result.file_merged_rows}`;
    }
    if (result.stock_mode) {
        message += `\nStock handling: ${result.stock_mode === 'set' ? 'set on-hand qty from file' : 'add qty to existing stock'}`;
    }
    if (result.errors && result.errors.length > 0) {
        message += `\n\nErrors: ${result.errors.length}`;
        if (result.errors.length <= 10) {
            message += '\n' + result.errors.join('\n');
        } else {
            message +=
                '\n' +
                result.errors.slice(0, 10).join('\n') +
                `\n… and ${result.errors.length - 10} more`;
        }
    }
    return message;
}

async function applyImportResult(result, options) {
    const messageEl =
        (options && options.messageEl) ||
        document.getElementById('import-message') ||
        document.getElementById('backup-message');

    if (messageEl) {
        messageEl.textContent = formatImportResultMessage(result);
        messageEl.style.color =
            result.errors && result.errors.length > 0
                ? 'rgba(251, 191, 36, 1)'
                : 'rgba(34, 197, 94, 1)';
    }

    if (result.created > 0 || result.updated > 0) {
        await loadAdminProducts();
    }

    if (
        (!options || options.autoCloseModal !== false) &&
        (!result.errors || result.errors.length === 0)
    ) {
        setTimeout(() => hideImportModal(), 3000);
    }
}

async function uploadInventoryViaAndroidBridge(options) {
    const messageEl =
        (options && options.messageEl) ||
        document.getElementById('import-message') ||
        document.getElementById('backup-message');
    const uploadBtn =
        (options && options.uploadBtn) || document.getElementById('btn-upload-inventory');

    if (!hasAndroidPendingImport()) {
        if (messageEl) messageEl.textContent = 'Please select a file';
        return null;
    }

    if (messageEl) {
        messageEl.textContent = 'Uploading and processing file…';
        messageEl.style.color = 'rgba(255, 255, 255, 0.9)';
    }
    if (uploadBtn) uploadBtn.disabled = true;

    try {
        const raw = PosAndroidImport.uploadPendingImport();
        const payload = JSON.parse(raw);
        if (!payload.ok) {
            throw new Error(payload.error || 'Import failed');
        }
        const result = payload.result || payload;
        await applyImportResult(result, options);
        return result;
    } catch (e) {
        console.error('Android import error:', e);
        if (messageEl) {
            messageEl.textContent = 'Import failed: ' + (e.message || String(e));
            messageEl.style.color = 'rgba(239, 68, 68, 1)';
        }
        return null;
    } finally {
        if (uploadBtn) uploadBtn.disabled = false;
    }
}

async function uploadInventoryCsvFile(file, options) {
    const messageEl =
        (options && options.messageEl) ||
        document.getElementById('import-message') ||
        document.getElementById('backup-message');
    const uploadBtn =
        (options && options.uploadBtn) || document.getElementById('btn-upload-inventory');

    if (!file && hasAndroidPendingImport()) {
        return uploadInventoryViaAndroidBridge(options);
    }

    if (!file) {
        if (messageEl) messageEl.textContent = 'Please select a CSV file';
        return null;
    }

    const token = getImportAuthToken();
    if (!token) {
        if (messageEl) messageEl.textContent = 'Not signed in. Open Admin from a logged-in account.';
        return null;
    }

    const formData = new FormData();
    formData.append('file', file);

    if (messageEl) {
        messageEl.textContent = 'Uploading and processing CSV…';
        messageEl.style.color = 'rgba(255, 255, 255, 0.9)';
    }
    if (uploadBtn) uploadBtn.disabled = true;

    try {
        const response = await fetch('/api/products/import', {
            method: 'POST',
            headers: { Authorization: 'Bearer ' + token },
            body: formData,
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(parseApiErrorText(errorText));
        }

        const result = await response.json();
        await applyImportResult(result, options);
        return result;
    } catch (e) {
        console.error('Import error:', e);
        if (messageEl) {
            messageEl.textContent = 'Import failed: ' + (e.message || 'Unknown error');
            messageEl.style.color = 'rgba(239, 68, 68, 1)';
        }
        return null;
    } finally {
        if (uploadBtn) uploadBtn.disabled = false;
    }
}

async function uploadInventoryFile(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    if (hasAndroidPendingImport()) {
        await uploadInventoryViaAndroidBridge();
        return;
    }
    const fileInput = document.getElementById('inventory-file-input');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        const messageEl = document.getElementById('import-message');
        if (messageEl) messageEl.textContent = 'Please select a file';
        return;
    }
    await uploadInventoryCsvFile(fileInput.files[0]);
}

function setupAdminEvents() {
    const btnAdminPos = document.getElementById('btn-admin-pos');
    if (btnAdminPos) {
        btnAdminPos.addEventListener('click', () => {
            window.location.href = '/';
        });
    }
    
    const btnSaveProduct = document.getElementById('btn-save-product');
    if (btnSaveProduct) {
        btnSaveProduct.addEventListener('click', saveProduct);
    }
    
    const btnClearProduct = document.getElementById('btn-clear-product');
    if (btnClearProduct) {
        btnClearProduct.addEventListener('click', clearProductForm);
    }
    
    const btnLoadReport = document.getElementById('btn-load-report');
    if (btnLoadReport) {
        btnLoadReport.addEventListener('click', loadReport);
    }
    
    // Settings buttons - only exist on /store-settings page, not on /admin page
    const btnSaveSettings = document.getElementById('btn-save-settings');
    if (btnSaveSettings) {
        btnSaveSettings.addEventListener('click', saveStoreSettings);
    }
    
    const btnAddCashier = document.getElementById('btn-add-cashier');
    if (btnAddCashier) {
        btnAddCashier.addEventListener('click', saveCashier);
    }
    
    const btnClearCashier = document.getElementById('btn-clear-cashier');
    if (btnClearCashier) {
        btnClearCashier.addEventListener('click', clearCashierForm);
    }
    
    // Product form show/hide - handle button click and text toggle
    const btnShowProductForm = document.getElementById('btn-show-product-form');
    if (btnShowProductForm) {
        console.log('Add Product button found, setting up click handler');
        btnShowProductForm.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('=== Add Product button clicked (event listener) ===');
            
            const btn = this;
            const formCard = document.getElementById('product-form-card');
            if (!formCard) {
                console.error('Form card not found');
                return false;
            }
            
            const isVisible = window.getComputedStyle(formCard).display !== 'none';
            console.log('Panel visible:', isVisible, 'Button current text:', btn.textContent);
            
            if (isVisible) {
                // Panel is open, close it
                console.log('Closing panel and setting button to Add Product');
                btn.textContent = '➕ Add Product';
                btn.innerHTML = '➕ Add Product';
                if (typeof clearProductForm === 'function') {
                    clearProductForm();
                }
            } else {
                // Panel is closed, open it
                console.log('Opening panel - setting button to Exit FIRST');
                // Update button text IMMEDIATELY and MULTIPLE times
                btn.textContent = 'Exit';
                btn.innerHTML = 'Exit';
                // Force it again
                setTimeout(() => {
                    btn.textContent = 'Exit';
                    btn.innerHTML = 'Exit';
                    console.log('Button text after setTimeout:', btn.textContent);
                }, 0);
                // Then show the form
            if (typeof showProductForm === 'function') {
                showProductForm();
            } else {
                console.error('showProductForm function not found!');
            }
                // Update again after showProductForm
                setTimeout(() => {
                    btn.textContent = 'Exit';
                    btn.innerHTML = 'Exit';
                    console.log('Button text after showProductForm:', btn.textContent);
                }, 10);
            }
            console.log('Button text at end of handler:', btn.textContent);
            return false;
        });
        console.log('Add Product button click handler attached');
    }
    // Note: btn-show-product-form only exists on /admin page, not on /store-settings page
    
    // Import inventory handlers
    const btnImport = document.getElementById('btn-import-inventory');
    const fileInput = document.getElementById('inventory-file-input');
    const btnUpload = document.getElementById('btn-upload-inventory');
    const btnCancelImport = document.getElementById('btn-cancel-import');
    const btnCloseImport = document.getElementById('btn-close-import');
    
    if (btnImport) {
        btnImport.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Import button clicked');
            showImportModal();
            return false;
        });
        console.log('Import button event listener added');
    }
    // Note: btn-import-inventory only exists on /admin page, not on /store-settings page
    
    // Set up file input handlers (will be set up again when modal opens)
    setupFileInputHandlers();
    
    if (btnUpload) {
        btnUpload.addEventListener('click', uploadInventoryFile);
    }
    
    if (btnCancelImport) {
        btnCancelImport.addEventListener('click', hideImportModal);
    }
    
    if (btnCloseImport) {
        btnCloseImport.addEventListener('click', hideImportModal);
    }
    
    // Factory reset button - check if it exists
    const btnFactoryResetEl = document.getElementById('btn-factory-reset');
    if (btnFactoryResetEl) {
        btnFactoryResetEl.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Factory reset button clicked');
            factoryReset().catch(err => {
                console.error('Error in factoryReset:', err);
                const msg = document.getElementById('reset-message');
                if (msg) {
                    msg.textContent = 'Error: ' + (err.message || 'Unknown error');
                    msg.style.color = 'rgba(220, 38, 38, 1)';
                }
            });
            return false;
        });
        console.log('Factory reset button listener added in setupAdminEvents');
    } else {
        console.warn('btn-factory-reset not found in setupAdminEvents');
    }
    
    // More Settings toggle button
    const btnMoreSettings = document.getElementById('btn-more-settings');
    if (btnMoreSettings) {
        btnMoreSettings.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            toggleMoreSettings();
            return false;
        });
    }
    
    // Floating icon toggles
    const btnToggleSettings = document.getElementById('btn-toggle-settings');
    const btnToggleReport = document.getElementById('btn-toggle-report');
    // btn-close-settings removed - settings are now on a dedicated page
    const btnCloseReport = document.getElementById('btn-close-report');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (btnToggleSettings) {
        // Settings button now navigates to /store-settings page (panel removed)
        console.log('Setting up settings button for page navigation');
        btnToggleSettings.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Settings button clicked - navigating to /store-settings');
            window.location.href = '/store-settings';
            return false;
        };
    }
    // Note: btn-toggle-settings only exists on /admin page, not on /store-settings page
    
    if (btnToggleReport) {
        btnToggleReport.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Report icon clicked');
            toggleReportPanel();
            return false;
        };
    }
    // Note: btn-toggle-report only exists on /admin page, not on /store-settings page
    
    // Close buttons
    // btn-close-settings removed - settings are now on a dedicated page at /store-settings
    // No need to handle close button for settings panel anymore
    
    if (btnCloseReport) {
        btnCloseReport.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closeAllPanels();
            return false;
        };
    }
    
    // Shifts panel toggle
    const btnToggleShifts = document.getElementById('btn-toggle-shifts');
    if (btnToggleShifts) {
        btnToggleShifts.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Shifts icon clicked');
            if (typeof window.toggleShiftsPanel === 'function') {
                window.toggleShiftsPanel();
            } else {
                console.error('toggleShiftsPanel function not found');
            }
            return false;
        };
    }
    // Note: btn-toggle-shifts only exists on /admin page, not on /store-settings page
    
    // Close on backdrop click
    if (backdrop) {
        backdrop.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closeAllPanels();
            return false;
        };
    }
    
    // Also close import modal when clicking backdrop
    const importModal = document.getElementById('import-inventory-modal');
    if (importModal && backdrop) {
        importModal.onclick = function(e) {
            // Only close if clicking the modal itself (not its children)
            if (e.target === importModal) {
                hideImportModal();
            }
        };
    }
}

window.addEventListener('load', async () => {
    console.log('=== ADMIN.JS LOADED AND RUNNING ===');
    if (!ensureAdmin()) {
        console.log('Admin check failed, exiting');
        return;
    }
    console.log('Admin check passed, continuing...');

    (async function showPlatformOwnerBannerIfEligible() {
        const banner = document.getElementById('platform-owner-banner');
        if (!banner) return;
        try {
            const token = localStorage.getItem('pos_token');
            if (!token) return;
            const res = await fetch('/api/platform/access', {
                headers: { Authorization: 'Bearer ' + token },
            });
            if (!res.ok) return;
            const data = await res.json();
            if (data && data.is_platform_owner) {
                banner.style.display = 'flex';
            }
        } catch (e) {
            console.warn('Platform owner banner check failed', e);
        }
    })();

    // Verify panels exist
    const settingsPanel = document.getElementById('store-settings-panel');
    const reportPanel = document.getElementById('summary-report-panel');
    const importModal = document.getElementById('import-inventory-modal');
    const backdrop = document.getElementById('panel-backdrop');
    const btnSettings = document.getElementById('btn-toggle-settings');
    const btnReport = document.getElementById('btn-toggle-report');
    const btnImport = document.getElementById('btn-import-inventory');
    
    // Debug logging removed - elements are checked properly with null checks
    // btn-import-inventory and import-inventory-modal only exist on /admin page
    
    console.log('Initialization check:', {
        settingsPanel: !!settingsPanel,
        reportPanel: !!reportPanel,
        importModal: !!importModal,
        backdrop: !!backdrop,
        btnSettings: !!btnSettings,
        btnReport: !!btnReport,
        btnImport: !!btnImport
    });
    
    // Ensure panels are hidden by default on page load
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    if (reportPanel) {
        reportPanel.style.setProperty('display', 'none', 'important');
    }
    if (importModal) {
        importModal.style.setProperty('display', 'none', 'important');
    }
    if (backdrop) {
        backdrop.style.setProperty('display', 'none', 'important');
    }
    
    // Set up click handlers directly
    if (btnSettings) {
        btnSettings.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Settings button clicked directly');
            if (settingsPanel && backdrop) {
                const isVisible = window.getComputedStyle(settingsPanel).display !== 'none';
                console.log('Settings panel visible?', isVisible);
                if (isVisible) {
                    settingsPanel.style.setProperty('display', 'none', 'important');
                    backdrop.style.setProperty('display', 'none', 'important');
                } else {
                    // Close report panel if open
                    if (reportPanel) {
                        reportPanel.style.setProperty('display', 'none', 'important');
                    }
                    // Show settings panel
                    settingsPanel.style.setProperty('display', 'block', 'important');
                    settingsPanel.style.setProperty('visibility', 'visible', 'important');
                    settingsPanel.style.setProperty('opacity', '1', 'important');
                    backdrop.style.setProperty('display', 'block', 'important');
                    backdrop.style.setProperty('visibility', 'visible', 'important');
                    console.log('Settings panel should be visible now');
                }
            }
            return false;
        };
        console.log('Settings button handler attached');
    }
    
    if (btnReport) {
        btnReport.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Report button clicked directly');
            if (reportPanel && backdrop) {
                const isVisible = window.getComputedStyle(reportPanel).display !== 'none';
                console.log('Report panel visible?', isVisible);
                if (isVisible) {
                    reportPanel.style.setProperty('display', 'none', 'important');
                    backdrop.style.setProperty('display', 'none', 'important');
                } else {
                    // Close settings panel if open
                    if (settingsPanel) {
                        settingsPanel.style.setProperty('display', 'none', 'important');
                    }
                    // Show report panel
                    reportPanel.style.setProperty('display', 'block', 'important');
                    reportPanel.style.setProperty('visibility', 'visible', 'important');
                    reportPanel.style.setProperty('opacity', '1', 'important');
                    backdrop.style.setProperty('display', 'block', 'important');
                    backdrop.style.setProperty('visibility', 'visible', 'important');
                    console.log('Report panel should be visible now');
                }
            }
            return false;
        };
        console.log('Report button handler attached');
    }
    
    const btnToggleWithdrawals = document.getElementById('btn-toggle-withdrawals');
    if (btnToggleWithdrawals) {
        // Button now navigates to full page, no need for panel handler
        // The inline onclick handler in HTML handles navigation
        console.log('Withdrawals button found (navigation handled by inline onclick)');
    }
    
    const btnCloseWithdrawals = document.getElementById('btn-close-withdrawals');
    if (btnCloseWithdrawals) {
        btnCloseWithdrawals.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closeAllPanels();
            return false;
        };
    }
    
    // Setup filter and search handlers for withdrawals
    const withdrawalReasonFilter = document.getElementById('withdrawal-filter-reason');
    const withdrawalSearch = document.getElementById('withdrawal-search');
    if (withdrawalReasonFilter) {
        withdrawalReasonFilter.addEventListener('change', filterAndRenderWithdrawals);
    }
    if (withdrawalSearch) {
        withdrawalSearch.addEventListener('input', filterAndRenderWithdrawals);
    }
    
    // Setup sync withdrawals button
    const btnSyncWithdrawals = document.getElementById('btn-sync-withdrawals-backup');
    if (btnSyncWithdrawals) {
        btnSyncWithdrawals.addEventListener('click', syncWithdrawalsToBackup);
    }
    
    // Set up import button handler directly (simplified, no cloning)
    console.log('=== SETTING UP IMPORT BUTTON ===');
    console.log('btnImport variable:', btnImport);
    if (btnImport) {
        console.log('Import button found, setting up handler');
        btnImport.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('=== Import button clicked ===');
            const modal = document.getElementById('import-inventory-modal');
            const backdropEl = document.getElementById('panel-backdrop');
            console.log('Modal exists:', !!modal, 'Backdrop exists:', !!backdropEl);
            
            if (modal && backdropEl) {
                // Close other panels if open
                if (settingsPanel) {
                    settingsPanel.style.setProperty('display', 'none', 'important');
                }
                if (reportPanel) {
                    reportPanel.style.setProperty('display', 'none', 'important');
                }
                // Show import modal
                modal.style.setProperty('display', 'block', 'important');
                modal.style.setProperty('visibility', 'visible', 'important');
                modal.style.setProperty('opacity', '1', 'important');
                modal.style.setProperty('z-index', '1000', 'important');
                backdropEl.style.setProperty('display', 'block', 'important');
                backdropEl.style.setProperty('visibility', 'visible', 'important');
                backdropEl.style.setProperty('z-index', '999', 'important');
                console.log('Import modal displayed. Modal computed display:', window.getComputedStyle(modal).display);
                
                // Set up file input handlers after modal is shown
                setTimeout(() => {
                    console.log('Setting up file input handlers...');
                    setupFileInputHandlers();
                    // Test if file input is accessible
                    const testInput = document.getElementById('inventory-file-input');
                    const testLabel = document.getElementById('inventory-file-label');
                    console.log('File input accessible:', !!testInput, 'File label accessible:', !!testLabel);
                    if (testInput) {
                        console.log('File input accept attribute:', testInput.accept);
                    }
                }, 200);
            } else {
                console.error('Import modal or backdrop not found:', { modal: !!modal, backdrop: !!backdropEl });
            }
            return false;
        };
        console.log('Import button handler attached successfully');
    }
    // Note: btn-import-inventory only exists on /admin page, not on /store-settings page
    // No error needed - this is expected behavior
    
    // Use event delegation as a fallback for the import button (only on /admin page)
    // This will work even if the button is added dynamically
    document.addEventListener('click', function(e) {
        if (e.target && e.target.id === 'btn-import-inventory') {
            console.log('=== Import button clicked via event delegation ===');
            e.preventDefault();
            e.stopPropagation();
            const modal = document.getElementById('import-inventory-modal');
            const backdropEl = document.getElementById('panel-backdrop');
            if (modal && backdropEl) {
                // Close other panels (if they exist)
                const settingsPanel = document.getElementById('store-settings-panel');
                const reportPanel = document.getElementById('summary-report-panel');
                if (settingsPanel) settingsPanel.style.setProperty('display', 'none', 'important');
                if (reportPanel) reportPanel.style.setProperty('display', 'none', 'important');
                // Show import modal
                modal.style.setProperty('display', 'block', 'important');
                modal.style.setProperty('visibility', 'visible', 'important');
                modal.style.setProperty('opacity', '1', 'important');
                backdropEl.style.setProperty('display', 'block', 'important');
                backdropEl.style.setProperty('visibility', 'visible', 'important');
                setTimeout(() => setupFileInputHandlers(), 100);
            }
            return false;
        }
    });
    
    setupAdminEvents();
    
    // Load saved theme
    loadTheme();
    
    // Also set up factory reset button directly in case setupAdminEvents doesn't catch it
    // Use a delay to ensure DOM is fully loaded
    setTimeout(() => {
        const btnFactoryReset = document.getElementById('btn-factory-reset');
        if (btnFactoryReset) {
            // Remove any existing listeners first
            const newBtn = btnFactoryReset.cloneNode(true);
            btnFactoryReset.parentNode.replaceChild(newBtn, btnFactoryReset);
            
            newBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('Factory reset button clicked (direct listener)');
                factoryReset().catch(err => {
                    console.error('Error in factoryReset:', err);
                });
                return false;
            });
            console.log('Factory reset button event listener attached (delayed)');
        }
        // Note: btn-factory-reset only exists on /store-settings page, not on /admin page
        // This is expected behavior, no error needed
    }, 500);
    
    // Setup stock qty input to only accept positive integers
    const stockInput = document.getElementById('prod-stock');
    if (stockInput) {
        stockInput.addEventListener('change', function(e) {
            const value = Math.max(0, Math.round(parseFloat(e.target.value) || 0));
            e.target.value = value;
        });
        stockInput.addEventListener('input', function(e) {
            // Prevent negative values while typing
            if (parseFloat(e.target.value) < 0) {
                e.target.value = 0;
            }
        });
    }
    
    initDates();
    
    // Load data in parallel for better performance - if any critical call fails with 401, it will redirect
    // Otherwise, we'll log the error but continue
    const loadPromises = [];
    
    // Load critical data in parallel
    loadPromises.push(
        loadStoreSettings().catch(e => {
            console.error('Failed to load store settings:', e);
        })
    );
    
    loadPromises.push(
        loadAdminProducts().catch(e => {
            console.error('Failed to load products:', e);
        })
    );
    
    loadPromises.push(
        loadCashiers().catch(e => {
            console.error('Failed to load cashiers:', e);
        })
    );
    
    // Wait for all critical data to load
    await Promise.all(loadPromises);
    
    // Load report after critical data (non-blocking)
    // Note: Report elements only exist on /admin page, not on /store-settings page
    try {
        await loadReport();
    } catch (e) {
        // Report loading may fail if elements don't exist (expected on /store-settings page)
        // Only log if it's not a missing element issue
        if (e.message && !e.message.includes('null')) {
            console.error('Failed to load report:', e);
        }
        // If it's a 401, adminApi already redirected, so we won't reach here
    }
    
    try {
    await loadBackupConfig();
    } catch (e) {
        console.error('Failed to load backup config:', e);
        // If it's a 401, adminApi already redirected, so we won't reach here
    }
    
    try {
    await loadBackupStatus();
    } catch (e) {
        console.error('Failed to load backup status:', e);
        // If it's a 401, adminApi already redirected, so we won't reach here
    }
    
    // Set up backup event handlers
    setupBackupEvents();
    
    // Periodically check backup status
    setInterval(loadBackupStatus, 30000); // Every 30 seconds
});

// ==================== BACKUP MANAGEMENT ====================

async function loadBackupConfig() {
    try {
        const config = await adminApi('/api/backup/config');
        
        // Only set values if elements exist (they're on /store-settings page, not /admin page)
        const backupEnabledEl = document.getElementById('backup-enabled');
        if (backupEnabledEl) backupEnabledEl.checked = config.enabled || false;
        
        const backupWebAppUrlEl = document.getElementById('backup-web-app-url');
        if (backupWebAppUrlEl) backupWebAppUrlEl.value = config.web_app_url || '';
        
        const backupApiKeyEl = document.getElementById('backup-api-key');
        if (backupApiKeyEl) backupApiKeyEl.value = config.api_key || '';
    } catch (e) {
        console.error('Error loading backup config:', e);
    }
}

async function loadBackupStatus() {
    try {
        const status = await adminApi('/api/backup/status');
        const statusText = status.enabled ? 'Enabled' : 'Disabled';
        const internetText = status.has_internet ? 'Connected' : 'Offline';
        const statusColor = status.enabled ? 'rgba(34, 197, 94, 1)' : 'rgba(107, 114, 128, 1)';
        const internetColor = status.has_internet ? 'rgba(34, 197, 94, 1)' : 'rgba(239, 68, 68, 1)';
        
        // Only set values if elements exist (they're on /store-settings page, not /admin page)
        const backupStatusTextEl = document.getElementById('backup-status-text');
        if (backupStatusTextEl) {
            backupStatusTextEl.textContent = statusText;
            backupStatusTextEl.style.color = statusColor;
        }
        
        const backupInternetStatusEl = document.getElementById('backup-internet-status');
        if (backupInternetStatusEl) {
            backupInternetStatusEl.textContent = internetText;
            backupInternetStatusEl.style.color = internetColor;
        }
        
        const backupPendingCountEl = document.getElementById('backup-pending-count');
        if (backupPendingCountEl) {
            backupPendingCountEl.textContent = status.pending_changes || 0;
        }
    } catch (e) {
        console.error('Error loading backup status:', e);
    }
}

async function saveBackupConfig() {
    const msg = document.getElementById('backup-message');
    msg.textContent = '';
    
    const config = {
        enabled: document.getElementById('backup-enabled').checked,
        web_app_url: document.getElementById('backup-web-app-url').value.trim(),
        api_key: document.getElementById('backup-api-key').value.trim()
    };
    
    if (config.enabled && !config.web_app_url) {
        msg.textContent = 'Web App URL is required when backup is enabled';
        msg.style.color = 'rgba(239, 68, 68, 1)';
        return;
    }
    
    try {
        await adminApi('/api/backup/config', {
            method: 'PUT',
            body: JSON.stringify(config)
        });
        msg.textContent = 'Backup configuration saved';
        msg.style.color = 'rgba(34, 197, 94, 1)';
        await loadBackupStatus();
    } catch (e) {
        console.error(e);
        msg.textContent = 'Failed to save configuration: ' + (e.message || 'Unknown error');
        msg.style.color = 'rgba(239, 68, 68, 1)';
    }
}

async function syncAllToBackup() {
    const msg = document.getElementById('backup-message');
    msg.textContent = 'Syncing all products to Google Sheets...';
    msg.style.color = 'rgba(255, 255, 255, 0.9)';
    
    try {
        const result = await adminApi('/api/backup/sync-all', {
            method: 'POST'
        });
        if (result.success) {
            msg.textContent = result.message || 'Sync completed successfully';
            msg.style.color = 'rgba(34, 197, 94, 1)';
        } else {
            msg.textContent = result.message || 'Sync failed';
            msg.style.color = 'rgba(239, 68, 68, 1)';
        }
        await loadBackupStatus();
    } catch (e) {
        console.error(e);
        msg.textContent = 'Sync failed: ' + (e.message || 'Unknown error');
        msg.style.color = 'rgba(239, 68, 68, 1)';
    }
}

async function processBackupQueue() {
    const msg = document.getElementById('backup-message');
    msg.textContent = 'Processing pending changes...';
    msg.style.color = 'rgba(255, 255, 255, 0.9)';
    
    try {
        const result = await adminApi('/api/backup/process-queue', {
            method: 'POST'
        });
        if (result.success) {
            msg.textContent = result.message || `Processed ${result.processed || 0} changes`;
            msg.style.color = 'rgba(34, 197, 94, 1)';
        } else {
            msg.textContent = result.message || 'Processing failed';
            msg.style.color = 'rgba(239, 68, 68, 1)';
        }
        await loadBackupStatus();
    } catch (e) {
        console.error(e);
        msg.textContent = 'Processing failed: ' + (e.message || 'Unknown error');
        msg.style.color = 'rgba(239, 68, 68, 1)';
    }
}

function triggerStoreSettingsCsvImport() {
    const input = document.getElementById('store-csv-file-input');
    if (input) input.click();
}

async function importFromBackup() {
    triggerStoreSettingsCsvImport();
}

async function exportProductsCSV() {
    try {
        const token = localStorage.getItem('pos_token');
        if (!token) {
            alert('Not authenticated. Please log in again.');
            return;
        }
        
        const response = await fetch('/api/products/export/csv', {
            method: 'GET',
            headers: {
                'Authorization': 'Bearer ' + token,
            },
        });
        
        if (!response.ok) {
            throw new Error('Export failed');
        }
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Get filename from Content-Disposition header or use default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'inventory_backup.csv';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="(.+)"/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }
        
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        const msg = document.getElementById('backup-message');
        if (msg) {
            msg.textContent = 'CSV file downloaded successfully! Upload it to Google Sheets for backup.';
            msg.style.color = 'rgba(34, 197, 94, 1)';
        }
    } catch (e) {
        console.error(e);
        const msg = document.getElementById('backup-message');
        if (msg) {
            msg.textContent = 'Export failed: ' + (e.message || 'Unknown error');
            msg.style.color = 'rgba(239, 68, 68, 1)';
        }
    }
}

function setupBackupEvents() {
    const btnSaveConfig = document.getElementById('btn-save-backup-config');
    const btnSyncAll = document.getElementById('btn-sync-all-backup');
    const btnProcessQueue = document.getElementById('btn-process-queue');
    const btnImport = document.getElementById('btn-import-backup');
    const btnExportCSV = document.getElementById('btn-export-csv');
    
    if (btnExportCSV) {
        btnExportCSV.addEventListener('click', exportProductsCSV);
    }
    if (btnSaveConfig) {
        btnSaveConfig.addEventListener('click', saveBackupConfig);
    }
    if (btnSyncAll) {
        btnSyncAll.addEventListener('click', syncAllToBackup);
    }
    if (btnProcessQueue) {
        btnProcessQueue.addEventListener('click', processBackupQueue);
    }
    if (btnImport) {
        btnImport.addEventListener('click', importFromBackup);
    }

    const storeCsvInput = document.getElementById('store-csv-file-input');
    if (storeCsvInput && !storeCsvInput.dataset.bound) {
        storeCsvInput.dataset.bound = '1';
        storeCsvInput.addEventListener('change', async function (e) {
            const file = e.target.files && e.target.files[0];
            if (file) {
                await uploadInventoryCsvFile(file, { autoCloseModal: false });
            }
            e.target.value = '';
        });
    }
}

// Theme management (only 3 themes: default, light, classic)
function applyTheme(themeName) {
    const allowed = ['default', 'light', 'classic'];
    const theme = allowed.includes(themeName) ? themeName : 'default';
    const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
    document.body.classList.remove(...themeClasses);
    document.documentElement.classList.remove(...themeClasses);
    if (theme !== 'default') {
        const cls = 'theme-' + theme;
        document.body.classList.add(cls);
        document.documentElement.classList.add(cls);
    }
    
    if (theme === 'light') {
        if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
    } else if (typeof window.hideLightThemeVideo === 'function') {
        window.hideLightThemeVideo();
    }
    localStorage.setItem('pos-theme', theme);
    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.theme === theme) btn.classList.add('active');
    });
}

function loadTheme() {
    const saved = localStorage.getItem('pos-theme') || 'default';
    const theme = ['default', 'light', 'classic'].includes(saved) ? saved : 'default';
    applyTheme(theme);
    if (theme === 'light') {
        setTimeout(() => {
            if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
        }, 100);
    }
}

// ==================== CASHIER SHIFT MANAGEMENT ====================

let activeShift = null;

async function loadActiveShift() {
    try {
        activeShift = await adminApi('/api/shifts/active');
        updateShiftUI();
    } catch (error) {
        console.error('Error loading active shift:', error);
        activeShift = null;
        updateShiftUI();
    }
}

async function loadShiftsHistory() {
    const listEl = document.getElementById('shifts-list');
    if (!listEl) return;
    
    try {
        const shifts = await adminApi('/api/shifts?limit=50');
        if (shifts.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:20px;color:rgba(255,255,255,0.5);">No shifts found</div>';
            return;
        }
        
        listEl.innerHTML = shifts.map(shift => {
            const startTime = new Date(shift.start_time).toLocaleString();
            const endTime = shift.end_time ? new Date(shift.end_time).toLocaleString() : 'Active';
            const duration = shift.end_time ? 
                Math.round((new Date(shift.end_time) - new Date(shift.start_time)) / 1000 / 60) + ' min' : 
                'Ongoing';
            
            return `
                <div style="background:rgba(255,255,255,0.05);padding:12px;border-radius:8px;margin-bottom:8px;border:1px solid rgba(255,255,255,0.1);">
                    <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:8px;">
                        <div>
                            <strong>${shift.cashier_name}</strong><br>
                            <small style="color:rgba(255,255,255,0.6);">${startTime} - ${endTime}</small>
                        </div>
                        <div style="text-align:right;">
                            <div><strong>$${parseFloat(shift.total_sales).toFixed(2)}</strong></div>
                            <small style="color:rgba(255,255,255,0.6);">${shift.total_transactions} transactions</small>
                        </div>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:12px;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.1);">
                        <div>Cash: $${parseFloat(shift.total_cash).toFixed(2)}</div>
                        <div>Mobile: $${parseFloat(shift.total_mobile_money).toFixed(2)}</div>
                        <div>Card: $${parseFloat(shift.total_card).toFixed(2)}</div>
                        <div>Credit: $${parseFloat(shift.total_credit).toFixed(2)}</div>
                    </div>
                    ${shift.end_time ? `<button onclick="viewShiftReport(${shift.id})" class="small" style="margin-top:8px;width:100%;">View Report</button>` : ''}
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading shifts:', error);
        listEl.innerHTML = '<div style="text-align:center;padding:20px;color:rgba(239,68,68,1);">Error loading shifts</div>';
    }
}

function updateShiftUI() {
    const activeSection = document.getElementById('active-shift-section');
    const noActiveSection = document.getElementById('no-active-shift-section');
    
    if (activeShift) {
        if (activeSection) activeSection.style.display = 'block';
        if (noActiveSection) noActiveSection.style.display = 'none';
        
        document.getElementById('active-shift-start').textContent = new Date(activeShift.start_time).toLocaleString();
        document.getElementById('active-shift-starting-cash').textContent = parseFloat(activeShift.starting_cash).toFixed(2);
        document.getElementById('active-shift-sales').textContent = parseFloat(activeShift.total_sales).toFixed(2);
        document.getElementById('active-shift-transactions').textContent = activeShift.total_transactions;
    } else {
        if (activeSection) activeSection.style.display = 'none';
        if (noActiveSection) noActiveSection.style.display = 'block';
    }
}

async function startShift() {
    const startingCash = parseFloat(document.getElementById('starting-cash').value) || 0;
    const notes = document.getElementById('shift-start-notes').value || null;
    const msgEl = document.getElementById('shift-message');
    
    if (startingCash < 0) {
        msgEl.textContent = 'Starting cash cannot be negative';
        msgEl.style.color = 'rgba(239,68,68,1)';
        return;
    }
    
    try {
        const shift = await adminApi('/api/shifts/start', {
            method: 'POST',
            body: JSON.stringify({
                starting_cash: startingCash,
                notes: notes
            })
        });
        
        activeShift = shift;
        updateShiftUI();
        document.getElementById('starting-cash').value = '';
        document.getElementById('shift-start-notes').value = '';
        msgEl.textContent = '✓ Shift started successfully';
        msgEl.style.color = 'rgba(16,185,129,1)';
        
        // Reload history
        loadShiftsHistory();
    } catch (error) {
        msgEl.textContent = 'Error: ' + (error.message || 'Failed to start shift');
        msgEl.style.color = 'rgba(239,68,68,1)';
    }
}

async function endShift() {
    const endingCash = parseFloat(document.getElementById('ending-cash').value);
    const notes = document.getElementById('shift-end-notes').value || null;
    const msgEl = document.getElementById('shift-message');
    
    if (isNaN(endingCash) || endingCash < 0) {
        msgEl.textContent = 'Please enter a valid ending cash amount';
        msgEl.style.color = 'rgba(239,68,68,1)';
        return;
    }
    
    if (!activeShift) {
        msgEl.textContent = 'No active shift found';
        msgEl.style.color = 'rgba(239,68,68,1)';
        return;
    }
    
    try {
        const report = await adminApi(`/api/shifts/${activeShift.id}/end`, {
            method: 'POST',
            body: JSON.stringify({
                ending_cash: endingCash,
                notes: notes
            })
        });
        
        activeShift = null;
        updateShiftUI();
        document.getElementById('ending-cash').value = '';
        document.getElementById('shift-end-notes').value = '';
        msgEl.textContent = '✓ Shift ended successfully. Report generated.';
        msgEl.style.color = 'rgba(16,185,129,1)';
        
        // Show report
        showShiftReport(report);
        
        // Reload history
        loadShiftsHistory();
    } catch (error) {
        msgEl.textContent = 'Error: ' + (error.message || 'Failed to end shift');
        msgEl.style.color = 'rgba(239,68,68,1)';
    }
}

async function viewShiftReport(shiftId) {
    try {
        const report = await adminApi(`/api/shifts/${shiftId}/report`);
        showShiftReport(report);
    } catch (error) {
        alert('Error loading report: ' + (error.message || 'Unknown error'));
    }
}

function showShiftReport(report) {
    const panel = document.getElementById('shift-report-panel');
    const content = document.getElementById('shift-report-content');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (!panel || !content) return;
    
    const shift = report.shift;
    const summary = report.summary;
    
    content.innerHTML = `
        <h3 style="margin:0 0 16px 0;">Shift Report - ${shift.cashier_name}</h3>
        <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:8px;margin-bottom:16px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
                <div><strong>Start Time:</strong> ${new Date(shift.start_time).toLocaleString()}</div>
                <div><strong>End Time:</strong> ${shift.end_time ? new Date(shift.end_time).toLocaleString() : 'N/A'}</div>
                <div><strong>Starting Cash:</strong> $${parseFloat(shift.starting_cash).toFixed(2)}</div>
                <div><strong>Ending Cash:</strong> $${shift.ending_cash ? parseFloat(shift.ending_cash).toFixed(2) : 'N/A'}</div>
            </div>
            ${summary.cash_difference !== null ? `
                <div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.2);">
                    <strong>Cash Difference:</strong> 
                    <span style="color:${summary.cash_difference >= 0 ? 'rgba(16,185,129,1)' : 'rgba(239,68,68,1)'};">
                        $${summary.cash_difference.toFixed(2)}
                    </span>
                </div>
            ` : ''}
        </div>
        
        <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:8px;margin-bottom:16px;">
            <h4 style="margin:0 0 12px 0;">Summary</h4>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;">
                <div>Total Sales: <strong>$${summary.total_sales.toFixed(2)}</strong></div>
                <div>Total Transactions: <strong>${summary.total_transactions}</strong></div>
                <div>Cash Payments: <strong>$${summary.total_cash.toFixed(2)}</strong></div>
                <div>Mobile Money: <strong>$${summary.total_mobile_money.toFixed(2)}</strong></div>
                <div>Card Payments: <strong>$${summary.total_card.toFixed(2)}</strong></div>
                <div>Credit Sales: <strong>$${summary.total_credit.toFixed(2)}</strong></div>
                <div>Total Discounts: <strong>$${summary.total_discounts.toFixed(2)}</strong></div>
            </div>
        </div>
        
        <div>
            <h4 style="margin:0 0 12px 0;">Transactions (${report.transactions.length})</h4>
            <div style="max-height:400px;overflow-y:auto;">
                ${report.transactions.length === 0 ? 
                    '<div style="text-align:center;padding:20px;color:rgba(255,255,255,0.5);">No transactions</div>' :
                    report.transactions.map(txn => `
                        <div style="background:rgba(255,255,255,0.05);padding:12px;border-radius:8px;margin-bottom:8px;border:1px solid rgba(255,255,255,0.1);">
                            <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                                <div>
                                    <strong>Transaction #${txn.id}</strong><br>
                                    <small style="color:rgba(255,255,255,0.6);">${new Date(txn.created_at).toLocaleString()}</small>
                                    ${txn.customer_name ? `<br><small>Customer: ${txn.customer_name}</small>` : ''}
                                </div>
                                <div style="text-align:right;">
                                    <strong>$${txn.total.toFixed(2)}</strong>
                                </div>
                            </div>
                            <div style="font-size:12px;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.1);">
                                <div><strong>Items:</strong></div>
                                ${txn.items.map(item => `
                                    <div style="margin-left:12px;margin-top:4px;">
                                        ${item.product_name} x${item.quantity} @ $${item.unit_price.toFixed(2)}
                                        ${item.discount > 0 ? ` (Disc: $${item.discount.toFixed(2)})` : ''}
                                        = $${item.line_total.toFixed(2)}
                                    </div>
                                `).join('')}
                                <div style="margin-top:8px;">
                                    <strong>Payments:</strong>
                                    ${Object.entries(txn.payment_methods).map(([method, amount]) => 
                                        `<span style="margin-left:8px;">${method}: $${amount.toFixed(2)}</span>`
                                    ).join('')}
                                </div>
                            </div>
                        </div>
                    `).join('')
                }
            </div>
        </div>
    `;
    
    panel.style.setProperty('display', 'block', 'important');
    panel.style.setProperty('visibility', 'visible', 'important');
    panel.style.setProperty('opacity', '1', 'important');
    if (backdrop) {
        backdrop.style.setProperty('display', 'block', 'important');
    }
}

// toggleShiftsPanel is defined earlier in the file (after toggleReportPanel)
// Duplicate removed - using the earlier definition

window.viewShiftReport = viewShiftReport;

// Add event listeners for shift management
document.addEventListener('DOMContentLoaded', function() {
    const btnStartShift = document.getElementById('btn-start-shift');
    const btnEndShift = document.getElementById('btn-end-shift');
    const btnCloseShifts = document.getElementById('btn-close-shifts');
    const btnCloseShiftReport = document.getElementById('btn-close-shift-report');
    const btnCloseShiftPasswordModal = document.getElementById('btn-close-shift-password-modal');
    const btnVerifyShiftPassword = document.getElementById('btn-verify-shift-password');
    const shiftPasswordInput = document.getElementById('shift-admin-password');
    const backdrop = document.getElementById('panel-backdrop');
    
    if (btnStartShift) {
        btnStartShift.addEventListener('click', startShift);
    }
    if (btnEndShift) {
        btnEndShift.addEventListener('click', endShift);
    }
    if (btnCloseShifts) {
        btnCloseShifts.addEventListener('click', () => {
            document.getElementById('shifts-panel').style.setProperty('display', 'none', 'important');
            if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
        });
    }
    if (btnCloseShiftReport) {
        btnCloseShiftReport.addEventListener('click', () => {
            document.getElementById('shift-report-panel').style.setProperty('display', 'none', 'important');
            if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
        });
    }
    
    // Password modal event listeners
    if (btnCloseShiftPasswordModal) {
        btnCloseShiftPasswordModal.addEventListener('click', () => {
            hideShiftPasswordModal();
            if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
        });
    }
    
    if (btnVerifyShiftPassword) {
        btnVerifyShiftPassword.addEventListener('click', verifyShiftPassword);
    }
    
    // Allow Enter key to submit password
    if (shiftPasswordInput) {
        shiftPasswordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                verifyShiftPassword();
            }
        });
    }
    
    // Load active shift on page load
    loadActiveShift();
});



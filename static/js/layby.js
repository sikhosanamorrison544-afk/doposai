let laybyToken = null;
let laybyUser = null;
let laybyCustomers = [];
let laybyProducts = [];
let laybyTransactions = [];
let selectedTransactionId = null;
let editingCustomerId = null;
let selectedCustomerId = null;
let currentPaymentHistory = [];
let currentPaymentHistoryTxn = null;

// Helper function to escape HTML
function escapeHtml(text) {
    if (text == null) return '-';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Check authentication
async function ensureAuthenticated() {
    const savedToken = localStorage.getItem('pos_token');
    const savedUser = localStorage.getItem('pos_user');
    if (savedToken && savedUser) {
        laybyToken = savedToken.trim(); // Remove any whitespace
        laybyUser = JSON.parse(savedUser);
        const userInfoEl = document.getElementById('layby-user-info');
        if (userInfoEl) {
            userInfoEl.textContent = `${laybyUser.username} (${laybyUser.role})`;
        }
        console.log('Authentication verified. Token length:', laybyToken.length);
        return true;
    }
    console.error('No authentication found in localStorage');
    window.location.href = '/';
    return false;
}

async function laybyApi(path, options = {}) {
    // Always refresh token from localStorage to ensure we have the latest
    const savedToken = localStorage.getItem('pos_token');
    if (savedToken && savedToken.trim()) {
        laybyToken = savedToken.trim();
    }
    
    if (!laybyToken || !laybyToken.trim()) {
        console.error('No authentication token available in localStorage');
        // Try to authenticate first
        const authenticated = await ensureAuthenticated();
        if (!authenticated) {
            throw new Error('Not authenticated. Please refresh the page and login again.');
        }
        // Try again after ensureAuthenticated
        const retryToken = localStorage.getItem('pos_token');
        if (retryToken && retryToken.trim()) {
            laybyToken = retryToken.trim();
        }
    }
    
    if (!laybyToken || !laybyToken.trim()) {
        console.error('Still no token after authentication check');
        throw new Error('Not authenticated. Please refresh the page and login again.');
    }
    
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    
    // Ensure Authorization header is set correctly - trim the token to remove any whitespace
    const cleanToken = laybyToken.trim();
    headers['Authorization'] = 'Bearer ' + cleanToken;
    
    console.log('API call:', path, options.method || 'GET');
    console.log('Token present:', !!cleanToken, 'Token length:', cleanToken.length);
    console.log('Authorization header format:', cleanToken ? 'Bearer ' + cleanToken.substring(0, 20) + '...' : 'missing');
    
    try {
    const res = await fetch(path, {
        ...options,
        headers,
    });
        
    console.log('API response status:', res.status, res.statusText);
        
    if (!res.ok) {
        const text = await res.text();
            console.error('API error response:', text);
            console.error('Request headers sent:', JSON.stringify(headers, null, 2));
        let errorMsg = text;
        try {
            const errorJson = JSON.parse(text);
            errorMsg = errorJson.detail || errorJson.message || text;
        } catch (e) {
            // Not JSON, use text as is
        }
            
            // If authentication fails, redirect to login
            if (res.status === 401) {
                console.error('Authentication failed (401) - token may be expired or invalid');
                console.error('Token that failed:', cleanToken ? cleanToken.substring(0, 30) + '...' : 'none');
                // Clear invalid token and redirect
                localStorage.removeItem('pos_token');
                localStorage.removeItem('pos_user');
                window.location.href = '/';
                return;
            }
            
        throw new Error(errorMsg || res.statusText);
    }
    if (res.status === 204) return null;
    const data = await res.json();
    console.log('API response data:', data);
    return data;
    } catch (error) {
        console.error('Fetch error:', error);
        throw error;
    }
}

// Customer Management
async function loadCustomers() {
    console.log('Loading customers...');
    try {
        // Add cache busting parameter to ensure fresh data
        const timestamp = new Date().getTime();
        const customers = await laybyApi(`/api/layby/customers?_=${timestamp}`);
        console.log('Raw customers data from API:', customers);
        console.log('Type of customers:', typeof customers, Array.isArray(customers));
        
        if (!Array.isArray(customers)) {
            console.error('API did not return an array!', customers);
            laybyCustomers = [];
        } else {
            laybyCustomers = customers;
        }
        
        console.log('✅ Customers loaded:', laybyCustomers.length, 'customers');
        console.log('📋 All customer IDs:', laybyCustomers.map(c => c.id).join(', '));
        
        if (laybyCustomers.length > 0) {
            console.log('📊 First customer full data:', JSON.stringify(laybyCustomers[0], null, 2));
            console.log('📊 First customer sample:', {
                id: laybyCustomers[0].id,
                name: laybyCustomers[0].name,
                phone: laybyCustomers[0].phone,
                address: laybyCustomers[0].address,
                email: laybyCustomers[0].email
            });
            if (laybyCustomers.length > 1) {
                console.log('📊 Last customer sample:', {
                    id: laybyCustomers[laybyCustomers.length - 1].id,
                    name: laybyCustomers[laybyCustomers.length - 1].name,
                    phone: laybyCustomers[laybyCustomers.length - 1].phone,
                    address: laybyCustomers[laybyCustomers.length - 1].address
                });
            }
        } else {
            console.warn('⚠️ No customers found in database');
        }
        
        renderCustomers();
        updateCustomerSelect();
    } catch (e) {
        console.error('❌ Error loading customers:', e);
        const errorMsg = e.message || 'Unknown error';
        console.error('Error details:', errorMsg);
        laybyCustomers = [];
        renderCustomers();
        
        // Show error message to user
        const tbody = document.getElementById('customers-body');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:40px;color:#ef4444;">Error loading customers: ${errorMsg}</td></tr>`;
        }
    }
}

function renderCustomers() {
    console.log('Rendering customers table. Total customers:', laybyCustomers.length);
    const tbody = document.getElementById('customers-body');
    if (!tbody) {
        console.error('customers-body element not found!');
        return;
    }
    
    // Update customer count
    const countEl = document.getElementById('customer-count');
    if (countEl) {
        countEl.textContent = `(${laybyCustomers.length} customer${laybyCustomers.length !== 1 ? 's' : ''})`;
    }
    
    tbody.innerHTML = '';
    
    if (laybyCustomers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:40px;color:#ffffff;">No layby customers found. Add a customer to get started.</td></tr>';
        return;
    }
    
    laybyCustomers.forEach((customer, index) => {
        console.log(`Rendering customer ${index + 1}:`, {
            id: customer.id,
            name: customer.name,
            phone: customer.phone,
            email: customer.email,
            address: customer.address,
            layby_item_name: customer.layby_item_name,
            active_items: customer.active_items
        });
        const tr = document.createElement('tr');
        // Display layby_item_name - this is the editable field stored in the database
        const laybyItemDisplay = (customer.layby_item_name && customer.layby_item_name.trim()) 
            ? customer.layby_item_name.trim() 
            : '-';
        // Display active_items - this is computed from transactions
        const activeItemsDisplay = (customer.active_items && customer.active_items.trim()) 
            ? customer.active_items.trim() 
            : '-';
        
        console.log(`Customer ${customer.id} - layby_item_name: "${customer.layby_item_name}", active_items: "${customer.active_items}"`);
        
        // Safely escape and get values
        const customerId = customer.id || customer.ID || '-';
        const customerName = (customer.name || customer.Name || '').trim() || '-';
        const customerPhone = (customer.phone || customer.Phone || '').trim() || '-';
        const customerAddress = (customer.address || customer.Address || '').trim() || '-';
        
        // Log for debugging
        if (index < 3) { // Log first 3 customers
            console.log(`Customer ${index + 1} data:`, {
                id: customerId,
                name: customerName,
                phone: customerPhone,
                address: customerAddress,
                raw: customer
            });
        }
        
        tr.innerHTML = `
            <td style="text-align:center;padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#ffffff !important;font-weight:bold;">${customerId}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#ffffff !important;">${escapeHtml(customerName)}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#ffffff !important;">${escapeHtml(customerPhone)}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#ffffff !important;">${escapeHtml(customerAddress)}</td>
            <td style="text-align:center;padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);">
                <button class="small btn-edit-customer" data-customer-id="${customerId}">Edit</button>
                <button class="small btn-select-customer" data-customer-id="${customerId}">Select</button>
                <button class="small danger btn-delete-customer" data-customer-id="${customerId}" data-customer-name="${escapeHtml(customerName)}">Delete</button>
            </td>
        `;
        
        // Add hover effect
        tr.style.transition = 'background-color 0.2s';
        tr.onmouseenter = () => tr.style.backgroundColor = 'rgba(255,255,255,0.1)';
        tr.onmouseleave = () => tr.style.backgroundColor = '';
        tbody.appendChild(tr);
        
        // Attach event listeners to the buttons
        const selectBtn = tr.querySelector('.btn-select-customer');
        const editBtn = tr.querySelector('.btn-edit-customer');
        const deleteBtn = tr.querySelector('.btn-delete-customer');
        
        if (selectBtn) {
            // Remove any existing event listeners to prevent duplicates
            const newSelectBtn = selectBtn.cloneNode(true);
            selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);
            
            // Create a clean handler function
            const handleSelectClick = async function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('🔵 Select button clicked for customer:', customer.id);
                
                const customerIdAttr = this.getAttribute('data-customer-id');
                const customerId = parseInt(customerIdAttr, 10);
                
                if (isNaN(customerId)) {
                    console.error('Invalid customer ID:', customerIdAttr);
                    alert('Error: Invalid customer ID');
                    return false;
                }
                
                // Call the select function
                try {
                    if (window.selectCustomerForTransaction) {
                        await window.selectCustomerForTransaction(customerId);
                            } else {
                        console.error('selectCustomerForTransaction function not found');
                        alert('Error: Function not available. Please refresh the page.');
                    }
                } catch (error) {
                    console.error('Error in selectCustomerForTransaction:', error);
                    alert('Error selecting customer: ' + (error.message || 'Unknown error'));
                }
                return false;
            };
            
            // Attach only one event listener
            newSelectBtn.addEventListener('click', handleSelectClick);
        }
        
        if (deleteBtn) {
            deleteBtn.addEventListener('click', async function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                const customerIdAttr = this.getAttribute('data-customer-id');
                const customerNameAttr = this.getAttribute('data-customer-name');
                const customerId = parseInt(customerIdAttr, 10);
                
                if (isNaN(customerId)) {
                    alert('Error: Invalid customer ID');
                    return false;
                }
                
                // Confirm deletion
                const confirmMsg = `Are you sure you want to delete customer "${customerNameAttr}"?\n\nThis will permanently delete:\n- The customer record\n- All associated layby transactions\n- All payment history\n\nThis action cannot be undone!`;
                if (!confirm(confirmMsg)) {
                    return false;
                }
                
                // Prompt for admin password
                const adminPassword = prompt('Enter admin password to confirm deletion:');
                if (!adminPassword) {
                    return false;
                }
                
                try {
                    // Use POST endpoint for deletion with password in body
                    const response = await laybyApi(`/api/layby/customers/${customerId}/delete`, {
                        method: 'POST',
                        body: JSON.stringify({ admin_password: adminPassword })
                    });
                    
                    // If we got here, deletion was successful
                    alert('Customer deleted successfully');
                    // Reload customers list
                    await loadCustomers();
                } catch (error) {
                    console.error('Error deleting customer:', error);
                    const errorMsg = error.message || 'Unknown error';
                    let errorText = errorMsg;
                    try {
                        const errorObj = JSON.parse(errorMsg);
                        if (errorObj.detail) {
                            errorText = errorObj.detail;
                    }
                    } catch (e) {
                        // Not JSON, use as-is
                    }
                    
                    if (errorText.includes('Invalid admin password') || errorText.includes('401') || errorText.includes('Invalid')) {
                        alert('Error: Invalid admin password. Deletion cancelled.');
        } else {
                        alert('Error deleting customer: ' + errorText);
                    }
                }
                
                return false;
            });
        }
        
        if (editBtn) {
            editBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const customerId = parseInt(this.getAttribute('data-customer-id'), 10);
                console.log('Edit button clicked for customer ID:', customerId);
                editCustomer(customerId);
            });
        }
    });
    
    const renderedCount = tbody.children.length;
    console.log('✅ Customers table rendered. Rows in table:', renderedCount);
    console.log('📊 Expected rows:', laybyCustomers.length);
    
    if (renderedCount !== laybyCustomers.length && laybyCustomers.length > 0) {
        console.warn('⚠️ Mismatch! Expected', laybyCustomers.length, 'rows but rendered', renderedCount);
    }
    
    // Verify table is visible and has content
    const tableContainer = document.getElementById('customers-table');
    if (tableContainer) {
        const computedStyle = window.getComputedStyle(tableContainer);
        console.log('📋 Table container visibility:', {
            display: computedStyle.display,
            visibility: computedStyle.visibility,
            opacity: computedStyle.opacity,
            height: computedStyle.height,
            overflow: computedStyle.overflow
        });
        
        // Check if any rows are visible
        const rows = tbody.querySelectorAll('tr');
        if (rows.length > 0) {
            const firstRow = rows[0];
            const firstRowStyle = window.getComputedStyle(firstRow);
            console.log('📋 First row visibility:', {
                display: firstRowStyle.display,
                visibility: firstRowStyle.visibility,
                color: firstRowStyle.color,
                backgroundColor: firstRowStyle.backgroundColor
            });
            
            // Log first row content
            const cells = firstRow.querySelectorAll('td');
            console.log('📋 First row cell count:', cells.length);
            cells.forEach((cell, idx) => {
                console.log(`  Cell ${idx + 1}:`, cell.textContent.trim());
            });
        }
    }
}

function updateCustomerSelect() {
    console.log('Updating customer select dropdown...');
    const select = document.getElementById('select-customer');
    if (!select) {
        // Element doesn't exist (removed panel), this is expected - just return silently
        console.log('select-customer element not found (panel removed) - skipping update');
        return;
    }
    select.innerHTML = '<option value="">Select Customer</option>';
    console.log('Customers to add to dropdown:', laybyCustomers.length);
    laybyCustomers.forEach(customer => {
        const option = document.createElement('option');
        option.value = customer.id;
        option.textContent = `${customer.name}${customer.phone ? ' - ' + customer.phone : ''}`;
        select.appendChild(option);
        console.log('Added option:', { value: option.value, text: option.textContent });
    });
    console.log('Customer select updated. Total options:', select.options.length);
}

// Function to edit customer
function editCustomer(customerId) {
    // Ensure customerId is a number
    const id = typeof customerId === 'string' ? parseInt(customerId, 10) : customerId;
    console.log('editCustomer called with ID:', id, 'Type:', typeof id);
    
    const customer = laybyCustomers.find(c => c.id === id || c.id === customerId);
    if (!customer) {
        console.error('Customer not found:', id, 'Available customers:', laybyCustomers.map(c => ({ id: c.id, name: c.name })));
        alert('Customer not found');
        return;
    }
    
    console.log('Editing customer:', customer);
    console.log('Customer data to populate:', {
        name: customer.name,
        phone: customer.phone,
        email: customer.email,
        address: customer.address
    });
    
    editingCustomerId = id; // Store as number
    
    // Get form elements
    const nameInput = document.getElementById('customer-name');
    const phoneInput = document.getElementById('customer-phone');
    const emailInput = document.getElementById('customer-email');
    const addressInput = document.getElementById('customer-address');
    const itemInput = document.getElementById('customer-layby-item');
    
    if (!nameInput || !phoneInput || !emailInput || !addressInput) {
        console.error('Form inputs not found!');
        alert('Error: Form inputs not found');
        return;
    }
    
    // Populate form
    nameInput.value = customer.name || '';
    phoneInput.value = customer.phone || '';
    emailInput.value = customer.email || '';
    addressInput.value = customer.address || '';
    if (itemInput) {
        itemInput.value = customer.layby_item_name || '';
    }
    
    console.log('Form populated. Current form values:');
    console.log('  name:', nameInput.value);
    console.log('  phone:', phoneInput.value);
    console.log('  email:', emailInput.value);
    console.log('  address:', addressInput.value);
    console.log('  layby_item_name:', itemInput ? itemInput.value : 'N/A');
    
    // Show the form if it's hidden
    const formContainer = document.getElementById('customer-form-container');
    if (formContainer && (formContainer.style.display === 'none' || formContainer.style.display === '')) {
        formContainer.style.display = 'block';
        const toggleText = document.getElementById('form-toggle-text');
        if (toggleText) {
            toggleText.textContent = 'Hide Add Customer Form';
        }
    }
    
    // Update form title and button
    document.getElementById('customer-form-title').textContent = `Edit Customer: ${customer.name}`;
    const saveBtn = document.getElementById('btn-save-customer');
    saveBtn.textContent = 'Update Customer';
    saveBtn.style.background = 'rgba(59, 130, 246, 0.8)';
    
    // Scroll to form
    setTimeout(() => {
        if (formContainer) {
            formContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            document.querySelector('.card').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        // Focus on name field so user can start editing
        nameInput.focus();
        nameInput.select();
    }, 100);
}

async function saveCustomer() {
    const msg = document.getElementById('customer-message');
    const saveBtn = document.getElementById('btn-save-customer');
    
    msg.textContent = '';
    msg.style.color = '';
    
    // Get form values
    const nameInput = document.getElementById('customer-name');
    const phoneInput = document.getElementById('customer-phone');
    const emailInput = document.getElementById('customer-email');
    const addressInput = document.getElementById('customer-address');
    const itemInput = document.getElementById('customer-layby-item');
    
    if (!nameInput || !phoneInput || !emailInput || !addressInput) {
        msg.textContent = 'Error: Form fields not found';
        msg.style.color = '#ef4444';
        return;
    }
    
    const name = nameInput.value.trim();
    const phone = phoneInput.value.trim() || null;
    const email = emailInput.value.trim() || null;
    const address = addressInput.value.trim() || null;
    const layby_item_name = itemInput ? itemInput.value.trim() || null : null;

    console.log('=== SAVE CUSTOMER DEBUG ===');
    console.log('Form input values:');
    console.log('  nameInput.value:', nameInput.value);
    console.log('  phoneInput.value:', phoneInput.value);
    console.log('  emailInput.value:', emailInput.value);
    console.log('  addressInput.value:', addressInput.value);
    console.log('  itemInput.value:', itemInput ? itemInput.value : 'N/A');
    console.log('Trimmed values:');
    console.log('  name:', name);
    console.log('  phone:', phone);
    console.log('  email:', email);
    console.log('  address:', address);
    console.log('  layby_item_name:', layby_item_name);
    console.log('editingCustomerId:', editingCustomerId, 'Type:', typeof editingCustomerId);
    
    if (!name) {
        msg.textContent = 'Name is required';
        msg.style.color = '#ef4444';
        return;
    }

    // Disable button during save
    saveBtn.disabled = true;
    saveBtn.textContent = editingCustomerId ? 'Updating...' : 'Saving...';

    try {
        let customer;
        if (editingCustomerId) {
            // Update existing customer
            const customerId = typeof editingCustomerId === 'string' ? parseInt(editingCustomerId, 10) : editingCustomerId;
            console.log('Updating customer ID:', customerId, 'Type:', typeof customerId);
            console.log('Update data:', { name, phone, email, address });
            const updateUrl = `/api/layby/customers/${customerId}`;
            console.log('Update URL:', updateUrl);
            
            const updatePayload = { name, phone, email, address, layby_item_name };
            console.log('Update payload:', updatePayload);
            
            customer = await laybyApi(updateUrl, {
                method: 'PUT',
                body: JSON.stringify(updatePayload),
            });
            
            console.log('Customer updated successfully:', customer);
            console.log('Full customer object:', JSON.stringify(customer, null, 2));
            if (customer && customer.id) {
                // Show success message with updated values
                const updateSummary = [
                    `Name: ${customer.name}`,
                    customer.phone ? `Phone: ${customer.phone}` : null,
                    customer.email ? `Email: ${customer.email}` : null,
                    customer.address ? `Address: ${customer.address}` : null
                ].filter(Boolean).join(', ');
                msg.textContent = `✅ Customer updated successfully! ${updateSummary}`;
                msg.style.color = '#10b981';
                msg.style.fontWeight = 'bold';
                msg.style.padding = '8px';
                msg.style.border = '2px solid #10b981';
                msg.style.borderRadius = '4px';
                
                // IMMEDIATELY update the customer in local array BEFORE reloading
                const index = laybyCustomers.findIndex(c => {
                    const match = c.id === customer.id || c.id === parseInt(customer.id) || parseInt(c.id) === customer.id;
                    return match;
                });
                console.log('Searching for customer ID:', customer.id, 'Type:', typeof customer.id);
                console.log('Found customer at index:', index);
                console.log('All customer IDs in array:', laybyCustomers.map(c => ({ id: c.id, type: typeof c.id })));
                
                if (index !== -1) {
                    console.log('BEFORE update - customer at index:', JSON.stringify(laybyCustomers[index], null, 2));
                    // Replace the entire customer object with the updated one
                    laybyCustomers[index] = { ...customer };
                    console.log('AFTER update - customer at index:', JSON.stringify(laybyCustomers[index], null, 2));
                    // Force immediate re-render
                    renderCustomers();
                    updateCustomerSelect();
                    console.log('✅ Table re-rendered with updated data immediately');
                } else {
                    console.warn('⚠️ Customer not found in local array, will reload from server');
                }
            } else {
                throw new Error('Invalid response from server');
            }
        } else {
            // Create new customer
            console.log('Creating new customer:', { name, phone, email, address, layby_item_name });
            customer = await laybyApi('/api/layby/customers', {
                method: 'POST',
                body: JSON.stringify({ name, phone, email, address, layby_item_name }),
            });
            console.log('Customer created:', customer);
            msg.textContent = `Customer "${customer.name}" added successfully!`;
            msg.style.color = '#10b981';
        }
        
        // Clear form
        const savedCustomerId = customer ? customer.id : null;
        clearCustomerForm();
        
        // Reload customers from server with cache busting to ensure fresh data
        console.log('Reloading customers list from server...');
        await loadCustomers();
        console.log('Customers list reloaded. Total customers:', laybyCustomers.length);
        
        // Verify and highlight the updated customer
        if (savedCustomerId) {
            const updatedCustomer = laybyCustomers.find(c => {
                const match = c.id === savedCustomerId || c.id === parseInt(savedCustomerId);
                if (match) {
                    console.log('Found updated customer:', {
                        id: c.id,
                        name: c.name,
                        phone: c.phone,
                        email: c.email,
                        address: c.address
                    });
                }
                return match;
            });
            
            if (updatedCustomer) {
                console.log('✅ Updated customer verified in list');
                // Scroll to and highlight the updated customer row
                setTimeout(() => {
                    // Try multiple selectors to find the row
                    let row = document.querySelector(`button[data-customer-id="${savedCustomerId}"]`)?.closest('tr');
                    
                    // If not found, try by data-id (for backwards compatibility)
                    if (!row) {
                        row = document.querySelector(`button[data-id="${savedCustomerId}"]`)?.closest('tr');
                    }
                    
                    // If still not found, try finding by customer ID in the first cell
                    if (!row) {
                        const rows = document.querySelectorAll('#customers-body tr');
                        for (const r of rows) {
                            const firstCell = r.querySelector('td:first-child');
                            if (firstCell && firstCell.textContent.trim() === String(savedCustomerId)) {
                                row = r;
                                break;
                            }
                        }
                    }
                    
                    // If still not found, try by customer name
                    if (!row && updatedCustomer) {
                        const rows = document.querySelectorAll('#customers-body tr');
                        for (const r of rows) {
                            const nameCell = r.querySelector('td:nth-child(2)');
                            if (nameCell && nameCell.textContent.trim() === updatedCustomer.name) {
                                row = r;
                                break;
                            }
                        }
                    }
                    
                    if (row) {
                        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        row.style.backgroundColor = '#d1fae5';
                        setTimeout(() => {
                            row.style.backgroundColor = '';
                        }, 3000);
                        console.log('✅ Row found and highlighted for customer ID:', savedCustomerId);
                    } else {
                        console.warn('⚠️ Could not find row for customer ID:', savedCustomerId, '- table may need to be refreshed');
                    }
                }, 300);
            } else {
                console.error('❌ Updated customer NOT found in list after reload!');
                console.log('Looking for ID:', savedCustomerId);
                console.log('Available IDs:', laybyCustomers.map(c => c.id));
            }
        }
    } catch (e) {
        console.error('Error saving customer:', e);
        msg.textContent = 'Error: ' + (e.message || 'Failed to save customer');
        msg.style.color = '#ef4444';
    } finally {
        // Re-enable button
        saveBtn.disabled = false;
        saveBtn.textContent = editingCustomerId ? 'Update Customer' : 'Add Customer';
    }
}

function clearCustomerForm() {
    console.log('Clearing customer form, editingCustomerId was:', editingCustomerId);
    editingCustomerId = null;
    document.getElementById('customer-name').value = '';
    document.getElementById('customer-phone').value = '';
    document.getElementById('customer-email').value = '';
    document.getElementById('customer-address').value = '';
    const itemInput = document.getElementById('customer-layby-item');
    if (itemInput) itemInput.value = '';
    document.getElementById('customer-message').textContent = '';
    
    // Reset form title and button
    document.getElementById('customer-form-title').textContent = 'Add Customer';
    const saveBtn = document.getElementById('btn-save-customer');
    saveBtn.textContent = 'Add Customer';
    saveBtn.style.background = '';
    saveBtn.disabled = false;
}

// Function to show customer history view
async function showCustomerHistory(customerId) {
    console.log('Showing customer history for ID:', customerId);
    
    // Ensure we have authentication before proceeding
    if (!laybyToken) {
        const savedToken = localStorage.getItem('pos_token');
        if (savedToken) {
            laybyToken = savedToken;
        } else {
            console.error('No token found - redirecting to login');
            const authenticated = await ensureAuthenticated();
            if (!authenticated) {
        return;
    }
        }
    }
    
    // Ensure customerId is a number
    const id = typeof customerId === 'string' ? parseInt(customerId, 10) : customerId;
    
    // Find the customer
    const customer = laybyCustomers.find(c => {
        const cId = typeof c.id === 'string' ? parseInt(c.id, 10) : c.id;
        return cId === id;
    });
    
    if (!customer) {
        console.error('Customer not found:', id);
        alert('Customer not found');
        return;
    }
    
    selectedCustomerId = id;
    
    // Hide customers view, show history view
    const customersView = document.getElementById('customers-view');
    const historyView = document.getElementById('customer-history-view');
    
    if (customersView) customersView.style.display = 'none';
    if (historyView) {
        historyView.style.display = 'block';
        
        // Update customer name display
        const customerNameSpan = document.getElementById('selected-customer-name');
        if (customerNameSpan) {
            customerNameSpan.textContent = customer.name;
        }
    }
    
    // Load and render transactions for this customer
    await loadTransactionsForCustomer(id);
            }

// Function to go back to customers view
function showCustomersView() {
    console.log('Showing customers view');
    
    selectedCustomerId = null;
        
    // Hide history view, show customers view
    const customersView = document.getElementById('customers-view');
    const historyView = document.getElementById('customer-history-view');
    
    if (historyView) historyView.style.display = 'none';
    if (customersView) customersView.style.display = 'block';
}

// Function to load transactions for a specific customer
async function loadTransactionsForCustomer(customerId) {
    try {
        // Ensure we're authenticated before making the API call
        // Refresh token from localStorage before API call
        const savedToken = localStorage.getItem('pos_token');
        if (savedToken) {
            laybyToken = savedToken;
        }
        
        if (!laybyToken) {
            console.error('No authentication token found in localStorage');
            const authenticated = await ensureAuthenticated();
            if (!authenticated) {
                const tbody = document.getElementById('transactions-body');
                if (tbody) {
                    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:#ef4444;">Authentication required. Please refresh the page.</td></tr>`;
                }
                return;
            }
        }
        
        console.log('Loading transactions for customer:', customerId);
        console.log('Token available:', laybyToken ? 'Yes (length: ' + laybyToken.length + ')' : 'No');
        
        const transactions = await laybyApi(`/api/layby/transactions?customer_id=${customerId}`);
        laybyTransactions = transactions;
        console.log('Loaded', transactions.length, 'transactions for customer', customerId);
        renderTransactions(customerId);
    } catch (e) {
        console.error('Error loading transactions:', e);
        console.error('Error details:', e.message, e.stack);
        const tbody = document.getElementById('transactions-body');
        if (tbody) {
            const errorMsg = e.message || 'Unknown error';
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:#ef4444;">Error loading transactions: ${escapeHtml(errorMsg)}</td></tr>`;
        }
    }
}

// Function to select customer for transaction - make it globally accessible
window.selectCustomerForTransaction = async function selectCustomerForTransaction(customerId) {
    console.log('=== selectCustomerForTransaction called ===');
    console.log('Customer ID received:', customerId, 'Type:', typeof customerId);
    
    // IMPORTANT: We do NOT navigate to /layby/customer/{id} - we show inline history instead
    
    if (!customerId || isNaN(customerId)) {
        console.error('Invalid customer ID:', customerId);
        alert('Error: Invalid customer ID');
        return;
    }
    
    // Ensure authentication before proceeding
    const authenticated = await ensureAuthenticated();
    if (!authenticated) {
        console.error('Not authenticated - redirecting to login');
        return;
    }
    
    // Show customer history view inline - NO navigation to /layby/customer/{id}
    console.log('Showing customer history inline for customer:', customerId);
    await showCustomerHistory(customerId);
    console.log('Customer history view displayed');
};

// Product Management
async function loadProducts() {
    laybyProducts = await laybyApi('/api/products');
    updateProductSelect();
}

function updateProductSelect() {
    const select = document.getElementById('select-product');
    if (!select) {
        // Element doesn't exist (removed panel), this is expected - just return silently
        console.log('select-product element not found (panel removed) - skipping update');
        return;
    }
    select.innerHTML = '<option value="">Select Product</option>';
    laybyProducts.forEach(product => {
        const option = document.createElement('option');
        option.value = product.id;
        option.textContent = `${product.name} - $${parseFloat(product.selling_price).toFixed(2)} (Stock: ${product.stock_qty})`;
        option.dataset.price = product.selling_price;
        select.appendChild(option);
    });
}

// Transaction Management
async function loadTransactions() {
    laybyTransactions = await laybyApi('/api/layby/transactions');
    // Only render if we're showing transactions (i.e., a customer is selected)
    if (selectedCustomerId !== null) {
        renderTransactions(selectedCustomerId);
    }
}

function renderTransactions(customerId = null) {
    const tbody = document.getElementById('transactions-body');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    // Filter transactions by customer if specified
    let transactionsToShow = laybyTransactions;
    if (customerId !== null) {
        transactionsToShow = laybyTransactions.filter(txn => txn.customer_id === customerId);
    }
    
    if (transactionsToShow.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:40px;color:#ffffff;">No transactions found.</td></tr>';
        return;
    }
    
    transactionsToShow.forEach(txn => {
        const tr = document.createElement('tr');
        const statusClass = txn.status === 'completed' ? 'success' : txn.status === 'cancelled' ? 'danger' : '';
        tr.innerHTML = `
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#f9fafb;">${txn.id}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#f9fafb;">${escapeHtml(txn.product_name)}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#f9fafb;">${txn.quantity}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#f9fafb;">$${parseFloat(txn.total_amount).toFixed(2)}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#f9fafb;">$${parseFloat(txn.paid_amount).toFixed(2)}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);color:#f9fafb;">$${parseFloat(txn.balance).toFixed(2)}</td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);"><span class="${statusClass}">${txn.status.toUpperCase()}</span></td>
            <td style="padding:12px;border-bottom:1px solid rgba(255,255,255,0.1);">
                ${txn.status === 'active' ? `<button class="small primary" onclick="openPaymentPanel(${txn.id})">Pay</button>` : ''}
                <button class="small" onclick="viewPaymentHistory(${txn.id})">History</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function createLaybyTransaction() {
    // This function is for the removed transaction panel - check if elements exist
    const selectCustomer = document.getElementById('select-customer');
    const selectProduct = document.getElementById('select-product');
    const quantityInput = document.getElementById('layby-quantity');
    const notesInput = document.getElementById('layby-notes');
    const msg = document.getElementById('layby-message');
    
    if (!selectCustomer || !selectProduct) {
        // Elements don't exist (panel removed) - this function is no longer used
        console.log('Transaction creation panel removed - function not available');
        if (msg) {
            msg.textContent = 'Transaction creation is now done from the main POS page.';
        }
        return;
    }
    
    if (msg) msg.textContent = '';
    const customerId = parseInt(selectCustomer.value, 10);
    const productId = parseInt(selectProduct.value, 10);
    const quantity = quantityInput ? parseInt(quantityInput.value, 10) || 1 : 1;
    const notes = notesInput ? notesInput.value.trim() || null : null;

    if (!customerId || !productId) {
        if (msg) msg.textContent = 'Please select customer and product';
        return;
    }

    try {
        const transaction = await laybyApi('/api/layby/transactions', {
            method: 'POST',
            body: JSON.stringify({ customer_id: customerId, product_id: productId, quantity, notes }),
        });
        if (msg) msg.textContent = `Layby transaction #${transaction.id} created successfully!`;
        selectCustomer.value = '';
        selectProduct.value = '';
        if (quantityInput) quantityInput.value = '1';
        if (notesInput) notesInput.value = '';
        await loadTransactions();
    } catch (e) {
        if (msg) msg.textContent = 'Error: ' + (e.message || 'Failed to create transaction');
    }
}

// Payment Panel
function openPaymentPanel(transactionId) {
    const txn = laybyTransactions.find(t => t.id === transactionId);
    if (!txn) return;

    selectedTransactionId = transactionId;
    document.getElementById('payment-txn-id').textContent = `#${txn.id}`;
    document.getElementById('payment-customer').textContent = txn.customer_name;
    document.getElementById('payment-product').textContent = `${txn.product_name} x${txn.quantity}`;
    document.getElementById('payment-total').textContent = `$${parseFloat(txn.total_amount).toFixed(2)}`;
    document.getElementById('payment-paid').textContent = `$${parseFloat(txn.paid_amount).toFixed(2)}`;
    document.getElementById('payment-balance').textContent = `$${parseFloat(txn.balance).toFixed(2)}`;
    document.getElementById('pay-amount').value = '';
    document.getElementById('pay-method').value = 'cash';
    document.getElementById('pay-notes').value = '';
    document.getElementById('payment-message').textContent = '';

    const panel = document.getElementById('payment-panel');
    const backdrop = document.getElementById('layby-backdrop');
    panel.style.setProperty('display', 'block', 'important');
    backdrop.style.setProperty('display', 'block', 'important');
}

function closePaymentPanel() {
    const panel = document.getElementById('payment-panel');
    const backdrop = document.getElementById('layby-backdrop');
    panel.style.setProperty('display', 'none', 'important');
    backdrop.style.setProperty('display', 'none', 'important');
    selectedTransactionId = null;
}

async function recordPayment() {
    const msg = document.getElementById('payment-message');
    msg.textContent = '';
    const amount = parseFloat(document.getElementById('pay-amount').value);
    const method = document.getElementById('pay-method').value;
    const notes = document.getElementById('pay-notes').value.trim() || null;

    if (!selectedTransactionId) {
        msg.textContent = 'No transaction selected';
        return;
    }

    if (!amount || amount <= 0) {
        msg.textContent = 'Please enter a valid payment amount';
        return;
    }

    try {
        const payment = await laybyApi('/api/layby/payments', {
            method: 'POST',
            body: JSON.stringify({
                transaction_id: selectedTransactionId,
                amount: amount,
                payment_method: method,
                notes: notes,
            }),
        });
        msg.textContent = `Payment recorded! Receipt: ${payment.receipt_number}`;
        
        // Reload transactions for the selected customer if viewing history
        if (selectedCustomerId !== null) {
            await loadTransactionsForCustomer(selectedCustomerId);
        } else {
        await loadTransactions();
        }
        
        setTimeout(() => {
            closePaymentPanel();
        }, 2000);
    } catch (e) {
        msg.textContent = 'Error: ' + (e.message || 'Failed to record payment');
    }
}

// Payment History - Navigate to full page
async function viewPaymentHistory(transactionId) {
    // Navigate to the payment history page
    window.location.href = `/layby/transaction/${transactionId}/payments`;
}

// Download Payment History as PDF
function downloadPaymentHistoryPDF() {
    if (!currentPaymentHistory || currentPaymentHistory.length === 0) {
        alert('No payment history to download');
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    
    // Store name (you might want to get this from the page or API)
    const storeName = document.querySelector('.shop-name')?.textContent || 'Store';
    
    // Transaction info
    const txn = currentPaymentHistoryTxn;
    const customerName = txn ? txn.customer_name : 'Unknown';
    const productName = txn ? txn.product_name : 'Unknown';
    const txnId = txn ? txn.id : 'N/A';
    
    // Title
    doc.setFontSize(18);
    doc.setFont(undefined, 'bold');
    doc.text('Payment History', 14, 20);
    
    // Store name
    doc.setFontSize(12);
    doc.setFont(undefined, 'normal');
    doc.text(storeName, 14, 30);
    
    // Transaction details
    doc.setFontSize(10);
    doc.text(`Transaction ID: ${txnId}`, 14, 40);
    doc.text(`Customer: ${customerName}`, 14, 46);
    doc.text(`Product: ${productName}`, 14, 52);
    if (txn) {
        doc.text(`Total Amount: $${parseFloat(txn.total_amount).toFixed(2)}`, 14, 58);
        doc.text(`Paid Amount: $${parseFloat(txn.paid_amount).toFixed(2)}`, 14, 64);
        doc.text(`Balance: $${parseFloat(txn.balance).toFixed(2)}`, 14, 70);
    }
    
    // Table header
    let yPos = 80;
    doc.setFontSize(10);
    doc.setFont(undefined, 'bold');
    doc.text('Date & Time', 14, yPos);
    doc.text('Amount', 80, yPos);
    doc.text('Method', 120, yPos);
    doc.text('Receipt #', 150, yPos);
    doc.text('Cashier', 180, yPos);
    
    // Draw line under header
    yPos += 3;
    doc.line(14, yPos, 196, yPos);
    yPos += 8;
    
    // Table data
    doc.setFont(undefined, 'normal');
    currentPaymentHistory.forEach((payment, index) => {
        if (yPos > 270) { // New page if needed
            doc.addPage();
            yPos = 20;
            // Redraw header on new page
            doc.setFont(undefined, 'bold');
            doc.text('Date & Time', 14, yPos);
            doc.text('Amount', 80, yPos);
            doc.text('Method', 120, yPos);
            doc.text('Receipt #', 150, yPos);
            doc.text('Cashier', 180, yPos);
            yPos += 3;
            doc.line(14, yPos, 196, yPos);
            yPos += 8;
            doc.setFont(undefined, 'normal');
        }
        
        const date = new Date(payment.created_at);
        const dateStr = date.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const timeStr = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        
        doc.setFontSize(9);
        doc.text(`${dateStr} ${timeStr}`, 14, yPos);
        doc.text(`$${parseFloat(payment.amount).toFixed(2)}`, 80, yPos);
        doc.text(payment.payment_method.toUpperCase(), 120, yPos);
        doc.text(payment.receipt_number || '-', 150, yPos);
        doc.text(payment.cashier_name || '-', 180, yPos);
        
        yPos += 7;
            });
    
    // Footer
    const totalPages = doc.internal.getNumberOfPages();
    for (let i = 1; i <= totalPages; i++) {
        doc.setPage(i);
        doc.setFontSize(8);
        doc.text(`Page ${i} of ${totalPages}`, 14, 285);
        doc.text(`Generated: ${new Date().toLocaleString()}`, 100, 285);
    }
    
    // Generate filename
    const filename = `payment_history_${customerName.replace(/\s+/g, '_')}_${txnId}_${new Date().toISOString().split('T')[0]}.pdf`;
    doc.save(filename);
}

// History panel removed - function no longer needed
// function closeHistoryPanel() {
//     const panel = document.getElementById('history-panel');
//     const backdrop = document.getElementById('history-backdrop');
//     panel.style.setProperty('display', 'none', 'important');
//     backdrop.style.setProperty('display', 'none', 'important');
// }

// Toggle customer form
function toggleCustomerForm() {
    const formContainer = document.getElementById('customer-form-container');
    const toggleBtn = document.getElementById('btn-toggle-customer-form');
    const toggleText = document.getElementById('form-toggle-text');
    
    if (formContainer && toggleBtn && toggleText) {
        const isVisible = formContainer.style.display !== 'none' && formContainer.style.display !== '';
        if (isVisible) {
            formContainer.style.display = 'none';
            toggleText.textContent = 'Show Add Customer Form';
        } else {
            formContainer.style.display = 'block';
            toggleText.textContent = 'Hide Add Customer Form';
        }
    }
}

// Event Handlers
function setupLaybyEvents() {
    document.getElementById('btn-back-pos').addEventListener('click', () => {
        window.location.href = '/';
    });
    document.getElementById('btn-layby-logout').addEventListener('click', () => {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.href = '/';
    });
    
    // Back to customers button
    const btnBackToCustomers = document.getElementById('btn-back-to-customers');
    if (btnBackToCustomers) {
        btnBackToCustomers.addEventListener('click', showCustomersView);
    }
    
    // Toggle customer form
    const btnToggleForm = document.getElementById('btn-toggle-customer-form');
    if (btnToggleForm) {
        btnToggleForm.addEventListener('click', toggleCustomerForm);
    }
    
    // View outstanding debts button
    const btnViewOutstandingDebts = document.getElementById('btn-view-outstanding-debts');
    console.log('Setting up btn-view-outstanding-debts handler, button found:', !!btnViewOutstandingDebts);
    if (btnViewOutstandingDebts) {
        btnViewOutstandingDebts.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('View Outstanding Debts button clicked');
            window.location.href = '/debts/outstanding';
            return false;
        });
        console.log('Event listener attached to btn-view-outstanding-debts');
    } else {
        console.error('btn-view-outstanding-debts button not found');
    }
    
    const btnSaveCustomer = document.getElementById('btn-save-customer');
    if (btnSaveCustomer) {
        btnSaveCustomer.addEventListener('click', saveCustomer);
    }
    
    const btnClearCustomer = document.getElementById('btn-clear-customer');
    if (btnClearCustomer) {
        btnClearCustomer.addEventListener('click', clearCustomerForm);
    }
    
    // Create layby button removed - transactions are now created from main POS page
    const btnRecordPayment = document.getElementById('btn-record-payment');
    if (btnRecordPayment) {
        btnRecordPayment.addEventListener('click', recordPayment);
    }
    
    const btnClosePayment = document.getElementById('btn-close-payment');
    if (btnClosePayment) {
        btnClosePayment.addEventListener('click', closePaymentPanel);
    }
    
    // History panel removed - no longer needed
    // All related event listeners have been removed
    
    const backdrop = document.getElementById('layby-backdrop');
    if (backdrop) {
        backdrop.addEventListener('click', closePaymentPanel);
    }
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
}

function loadTheme() {
    const savedTheme = localStorage.getItem('pos-theme') || 'default';
    applyTheme(savedTheme);
}

// Listen for theme changes from other pages
window.addEventListener('storage', function(e) {
    if (e.key === 'pos-theme') {
        applyTheme(e.newValue || 'default');
    }
});

// Also check for theme changes periodically (in case same-tab changes)
let lastTheme = localStorage.getItem('pos-theme') || 'default';
setInterval(() => {
    const currentTheme = localStorage.getItem('pos-theme') || 'default';
    if (currentTheme !== lastTheme) {
        lastTheme = currentTheme;
        applyTheme(currentTheme);
    }
}, 500);

// Initialize
window.addEventListener('load', async () => {
    const authenticated = await ensureAuthenticated();
    if (!authenticated) return;
    
    // Load theme first
    loadTheme();
    
    setupLaybyEvents();
    await loadCustomers();
    await loadProducts();
    // Don't load transactions initially - only load when a customer is selected
    // await loadTransactions();
    
    // Refresh transactions every 30 seconds if a customer is selected
    setInterval(() => {
        if (selectedCustomerId !== null) {
            loadTransactionsForCustomer(selectedCustomerId);
        }
    }, 30000);
});


/**
 * Quotation Management JavaScript
 * Handles quotation creation, editing, and management
 */

let quotationsToken = null;
let quotationsUser = null;
let allProducts = [];
let currentQuotation = null;
let quotationItems = [];

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    checkAuth();
    setupEventListeners();
    loadProducts();
    loadQuotations();
});

async function checkAuth() {
    const savedToken = localStorage.getItem('pos_token');
    const savedUser = localStorage.getItem('pos_user');
    
    if (!savedToken || !savedUser) {
        window.location.href = '/';
        return;
    }
    
    quotationsToken = savedToken;
    try {
        quotationsUser = JSON.parse(savedUser);
        const userInfoEl = document.getElementById('quotations-user-info');
        if (userInfoEl) {
            userInfoEl.textContent = `Logged in as: ${quotationsUser.username} (${quotationsUser.role})`;
        }
    } catch (e) {
        console.error('Error parsing user data:', e);
    }
}

async function quotationsApi(path, options = {}) {
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    if (quotationsToken) {
        headers['Authorization'] = 'Bearer ' + quotationsToken;
    }
    
    const res = await fetch(path, {
        ...options,
        headers,
    });
    
    if (!res.ok) {
        if (res.status === 401) {
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            window.location.href = '/';
            return;
        }
        const text = await res.text();
        throw new Error(text || res.statusText);
    }
    
    if (res.status === 204) return null;
    return res.json();
}

function setupEventListeners() {
    // Navigation
    document.getElementById('btn-back-admin')?.addEventListener('click', () => {
        window.location.href = '/admin';
    });
    
    document.getElementById('btn-quotations-logout')?.addEventListener('click', () => {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.href = '/';
    });
    
    // Quotation management
    document.getElementById('btn-create-quotation')?.addEventListener('click', showCreateModal);
    document.getElementById('btn-close-modal')?.addEventListener('click', closeModal);
    document.getElementById('btn-cancel-quotation')?.addEventListener('click', closeModal);
    document.getElementById('btn-save-quotation')?.addEventListener('click', saveQuotation);
    document.getElementById('btn-apply-filters')?.addEventListener('click', loadQuotations);
    document.getElementById('btn-clear-filters')?.addEventListener('click', clearFilters);
    
    // Product search
    const productSearch = document.getElementById('product-search');
    if (productSearch) {
        productSearch.addEventListener('input', handleProductSearch);
    }
    
    // Detail modal
    document.getElementById('btn-close-detail-modal')?.addEventListener('click', closeDetailModal);
    document.getElementById('btn-download-pdf')?.addEventListener('click', downloadQuotationPDF);
    document.getElementById('btn-convert-sale')?.addEventListener('click', showConvertSaleModal);
    document.getElementById('btn-delete-quotation')?.addEventListener('click', deleteQuotation);
    
    // Backdrop click to close modals
    document.getElementById('panel-backdrop')?.addEventListener('click', () => {
        closeModal();
        closeDetailModal();
    });
}

async function loadProducts() {
    try {
        allProducts = await quotationsApi('/api/products');
        console.log(`Loaded ${allProducts.length} products`);
    } catch (e) {
        console.error('Error loading products:', e);
    }
}

async function loadQuotations() {
    const status = document.getElementById('filter-status').value;
    const customer = document.getElementById('filter-customer').value.trim();
    const phone = document.getElementById('filter-phone').value.trim();
    const listEl = document.getElementById('quotations-list');
    const loadingEl = document.getElementById('loading-indicator');
    
    try {
        loadingEl.style.display = 'block';
        listEl.innerHTML = '';
        
        const params = new URLSearchParams();
        if (status) params.append('status', status);
        if (customer) params.append('customer_id', customer);
        if (phone) params.append('customer_phone', phone);
        
        const data = await quotationsApi(`/api/quotations?${params}`);
        
        loadingEl.style.display = 'none';
        
        if (data.quotations && data.quotations.length > 0) {
            listEl.innerHTML = data.quotations.map(q => `
                <div class="quotation-item" onclick="viewQuotation(${q.id})">
                    <div style="display: flex; justify-content: space-between; align-items: start;">
                        <div style="flex: 1;">
                            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                                <strong>${q.quotation_number}</strong>
                                <span class="quotation-status status-${q.status}">${q.status.toUpperCase()}</span>
                            </div>
                            <div>Customer: ${q.customer_name || 'N/A'}</div>
                            <div>Total: $${parseFloat(q.total).toFixed(2)}</div>
                            <div style="font-size: 0.9em; color: rgba(255,255,255,0.7); margin-top: 5px;">
                                Created: ${new Date(q.created_at).toLocaleString()}
                            </div>
                        </div>
                        <div style="margin-left: 15px;">
                            <button class="small" onclick="event.stopPropagation(); viewQuotation(${q.id})">View</button>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            listEl.innerHTML = '<div style="padding: 20px; text-align: center;">No quotations found</div>';
        }
    } catch (e) {
        loadingEl.style.display = 'none';
        listEl.innerHTML = `<div style="padding: 20px; text-align: center; color: #ef4444;">Error loading quotations: ${e.message}</div>`;
    }
}

function clearFilters() {
    document.getElementById('filter-status').value = '';
    document.getElementById('filter-customer').value = '';
    document.getElementById('filter-phone').value = '';
    loadQuotations();
}

function showCreateModal() {
    currentQuotation = null;
    quotationItems = [];
    document.getElementById('modal-title').textContent = 'Create Quotation';
    document.getElementById('quotation-customer-name').value = '';
    document.getElementById('quotation-customer-phone').value = '';
    document.getElementById('quotation-customer-email').value = '';
    document.getElementById('quotation-valid-until').value = '';
    document.getElementById('quotation-notes').value = '';
    document.getElementById('quotation-items').innerHTML = '';
    document.getElementById('quotation-total').textContent = '$0.00';
    document.getElementById('quotation-message').textContent = '';
    
    const modal = document.getElementById('quotation-modal');
    const backdrop = document.getElementById('panel-backdrop');
    modal.style.display = 'block';
    backdrop.style.display = 'block';
}

function closeModal() {
    document.getElementById('quotation-modal').style.display = 'none';
    document.getElementById('panel-backdrop').style.display = 'none';
}

function handleProductSearch(e) {
    const query = e.target.value.trim().toLowerCase();
    const resultsEl = document.getElementById('product-search-results');
    
    if (query.length < 2) {
        resultsEl.style.display = 'none';
        return;
    }
    
    const matches = allProducts.filter(p => 
        p.is_active && p.name.toLowerCase().includes(query)
    ).slice(0, 10);
    
    if (matches.length > 0) {
        resultsEl.innerHTML = matches.map(p => `
            <div class="product-search-item" onclick="addProductToQuotation(${p.id}, '${p.name.replace(/'/g, "\\'")}', ${p.selling_price}, ${p.stock_qty})">
                <strong>${p.name}</strong> - $${parseFloat(p.selling_price).toFixed(2)} (Stock: ${p.stock_qty})
            </div>
        `).join('');
        resultsEl.style.display = 'block';
    } else {
        resultsEl.innerHTML = '<div style="padding: 10px;">No products found</div>';
        resultsEl.style.display = 'block';
    }
}

function addProductToQuotation(productId, productName, price, stock) {
    // Check if already added
    const existing = quotationItems.find(item => item.product_id === productId);
    if (existing) {
        existing.quantity += 1;
    } else {
        quotationItems.push({
            product_id: productId,
            product_name: productName,
            quantity: 1,
            unit_price: parseFloat(price),
            discount: 0
        });
    }
    
    updateQuotationItemsDisplay();
    document.getElementById('product-search').value = '';
    document.getElementById('product-search-results').style.display = 'none';
}

function updateQuotationItemsDisplay() {
    const itemsEl = document.getElementById('quotation-items');
    const totalEl = document.getElementById('quotation-total');
    
    if (quotationItems.length === 0) {
        itemsEl.innerHTML = '<div style="padding: 10px; color: rgba(255,255,255,0.6);">No items added</div>';
        totalEl.textContent = '$0.00';
        return;
    }
    
    let total = 0;
    itemsEl.innerHTML = quotationItems.map((item, idx) => {
        const lineTotal = (item.unit_price * item.quantity) - item.discount;
        total += lineTotal;
        return `
            <div class="quotation-item-row">
                <div style="flex: 1;">
                    <strong>${item.product_name}</strong><br>
                    <span style="font-size: 0.9em;">Qty: ${item.quantity} x $${item.unit_price.toFixed(2)} = $${lineTotal.toFixed(2)}</span>
                </div>
                <div>
                    <input type="number" value="${item.quantity}" min="1" 
                           onchange="updateItemQuantity(${idx}, this.value)" 
                           style="width: 60px; margin-right: 5px;">
                    <button class="danger small" onclick="removeQuotationItem(${idx})">Remove</button>
                </div>
            </div>
        `;
    }).join('');
    
    totalEl.textContent = '$' + total.toFixed(2);
}

function updateItemQuantity(idx, quantity) {
    const qty = parseInt(quantity) || 1;
    if (qty < 1) {
        alert('Quantity must be at least 1');
        return;
    }
    quotationItems[idx].quantity = qty;
    updateQuotationItemsDisplay();
}

function removeQuotationItem(idx) {
    quotationItems.splice(idx, 1);
    updateQuotationItemsDisplay();
}

async function saveQuotation() {
    const customerName = document.getElementById('quotation-customer-name').value.trim();
    const customerPhone = document.getElementById('quotation-customer-phone').value.trim();
    const customerEmail = document.getElementById('quotation-customer-email').value.trim();
    const validUntil = document.getElementById('quotation-valid-until').value;
    const notes = document.getElementById('quotation-notes').value.trim();
    const messageEl = document.getElementById('quotation-message');
    
    if (!customerName) {
        messageEl.textContent = 'Customer name is required';
        messageEl.style.color = '#ef4444';
        return;
    }
    
    if (quotationItems.length === 0) {
        messageEl.textContent = 'Please add at least one product';
        messageEl.style.color = '#ef4444';
        return;
    }
    
    try {
        messageEl.textContent = 'Saving...';
        messageEl.style.color = '#3b82f6';
        
        const items = quotationItems.map(item => ({
            product_id: item.product_id,
            quantity: item.quantity,
            unit_price: item.unit_price,
            discount: item.discount || 0
        }));
        
        const data = {
            customer_name: customerName,
            customer_phone: customerPhone || null,
            customer_email: customerEmail || null,
            items: items,
            valid_until: validUntil || null,
            notes: notes || null
        };
        
        const quotation = await quotationsApi('/api/quotations', {
            method: 'POST',
            body: JSON.stringify(data)
        });
        
        messageEl.textContent = '✅ Quotation created successfully!';
        messageEl.style.color = '#22c55e';
        
        setTimeout(() => {
            closeModal();
            loadQuotations();
        }, 1500);
    } catch (e) {
        messageEl.textContent = '❌ Error: ' + e.message;
        messageEl.style.color = '#ef4444';
    }
}

async function viewQuotation(id) {
    try {
        const quotation = await quotationsApi(`/api/quotations/${id}`);
        currentQuotation = quotation;
        
        const contentEl = document.getElementById('quotation-detail-content');
        contentEl.innerHTML = `
            <div style="margin-bottom: 20px;">
                <div><strong>Quotation Number:</strong> ${quotation.quotation_number}</div>
                <div><strong>Status:</strong> <span class="quotation-status status-${quotation.status}">${quotation.status.toUpperCase()}</span></div>
                <div><strong>Customer:</strong> ${quotation.customer_name || 'N/A'}</div>
                ${quotation.customer_phone ? `<div><strong>Phone:</strong> ${quotation.customer_phone}</div>` : ''}
                ${quotation.customer_email ? `<div><strong>Email:</strong> ${quotation.customer_email}</div>` : ''}
                <div><strong>Valid Until:</strong> ${quotation.valid_until ? new Date(quotation.valid_until).toLocaleDateString() : 'N/A'}</div>
                <div><strong>Created:</strong> ${new Date(quotation.created_at).toLocaleString()}</div>
            </div>
            
            <h3>Items:</h3>
            <table style="width: 100%; margin: 10px 0;">
                <thead>
                    <tr>
                        <th>Product</th>
                        <th>Qty</th>
                        <th>Price</th>
                        <th>Total</th>
                    </tr>
                </thead>
                <tbody>
                    ${quotation.items.map(item => `
                        <tr>
                            <td>${item.product_name}</td>
                            <td>${item.quantity}</td>
                            <td>$${parseFloat(item.unit_price).toFixed(2)}</td>
                            <td>$${parseFloat(item.line_total).toFixed(2)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            
            <div style="margin-top: 20px; text-align: right; font-size: 1.2em; font-weight: bold;">
                <div>Subtotal: $${parseFloat(quotation.subtotal).toFixed(2)}</div>
                ${parseFloat(quotation.discount_total) > 0 ? `<div>Discount: $${parseFloat(quotation.discount_total).toFixed(2)}</div>` : ''}
                <div>Total: $${parseFloat(quotation.total).toFixed(2)}</div>
            </div>
            
            ${quotation.notes ? `<div style="margin-top: 20px;"><strong>Notes:</strong> ${quotation.notes}</div>` : ''}
        `;
        
        // Show/hide buttons based on status
        const convertBtn = document.getElementById('btn-convert-sale');
        const deleteBtn = document.getElementById('btn-delete-quotation');
        if (convertBtn) {
            convertBtn.style.display = quotation.status === 'sent' || quotation.status === 'accepted' ? 'inline-block' : 'none';
        }
        if (deleteBtn) {
            deleteBtn.style.display = quotation.status === 'draft' ? 'inline-block' : 'none';
        }
        
        const modal = document.getElementById('quotation-detail-modal');
        const backdrop = document.getElementById('panel-backdrop');
        modal.style.display = 'block';
        backdrop.style.display = 'block';
    } catch (e) {
        alert('Error loading quotation: ' + e.message);
    }
}

function closeDetailModal() {
    document.getElementById('quotation-detail-modal').style.display = 'none';
    document.getElementById('panel-backdrop').style.display = 'none';
}

async function downloadQuotationPDF() {
    if (!currentQuotation) return;
    
    try {
        const response = await fetch(`/api/quotations/${currentQuotation.id}/pdf`, {
            headers: {
                'Authorization': 'Bearer ' + quotationsToken
            }
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `quotation_${currentQuotation.quotation_number}.pdf`;
            a.click();
            window.URL.revokeObjectURL(url);
        } else {
            throw new Error('Failed to download PDF');
        }
    } catch (e) {
        alert('Error downloading PDF: ' + e.message);
    }
}

function showConvertSaleModal() {
    if (!currentQuotation) return;
    
    const cash = prompt('Enter cash amount (or 0):', '0');
    if (cash === null) return;
    
    const mobile = prompt('Enter mobile money amount (or 0):', '0');
    if (mobile === null) return;
    
    const card = prompt('Enter card amount (or 0):', '0');
    if (card === null) return;
    
    const payments = [];
    if (parseFloat(cash) > 0) payments.push({ method: 'cash', amount: parseFloat(cash) });
    if (parseFloat(mobile) > 0) payments.push({ method: 'mobile_money', amount: parseFloat(mobile) });
    if (parseFloat(card) > 0) payments.push({ method: 'card', amount: parseFloat(card) });
    
    if (payments.length === 0) {
        alert('Please enter at least one payment method');
        return;
    }
    
    convertQuotationToSale(payments);
}

async function convertQuotationToSale(payments) {
    if (!currentQuotation) return;
    
    try {
        const result = await quotationsApi(`/api/quotations/${currentQuotation.id}/convert-to-sale`, {
            method: 'POST',
            body: JSON.stringify({ payments: payments })
        });
        
        alert(`✅ Quotation converted to sale #${result.sale_id}!`);
        closeDetailModal();
        loadQuotations();
    } catch (e) {
        alert('Error converting quotation: ' + e.message);
    }
}

async function deleteQuotation() {
    if (!currentQuotation) return;
    
    if (!confirm(`Are you sure you want to delete quotation ${currentQuotation.quotation_number}?`)) {
        return;
    }
    
    try {
        await quotationsApi(`/api/quotations/${currentQuotation.id}`, {
            method: 'DELETE'
        });
        
        alert('✅ Quotation deleted successfully!');
        closeDetailModal();
        loadQuotations();
    } catch (e) {
        alert('Error deleting quotation: ' + e.message);
    }
}

// Make functions available globally for onclick handlers
window.viewQuotation = viewQuotation;
window.addProductToQuotation = addProductToQuotation;
window.updateItemQuantity = updateItemQuantity;
window.removeQuotationItem = removeQuotationItem;

